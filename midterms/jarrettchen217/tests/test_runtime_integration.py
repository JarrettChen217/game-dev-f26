"""Desktop and evaluation retain the pre-refactor accepted tapes and trace rows."""
import gzip
import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from tank_game.app import DrivingApp
from tank_game.controllers import BufferedController, keyboard_request
from tank_game.evaluation import run_game
from tank_game.observation_compat import project_public_scene
from tank_game.runner import MatchRunner
from tank_game.world import World
from tests.test_driving import open_map
from tests.test_driving_app import WindowStub
from tests.test_realtime import Clock

FIXTURES = Path(__file__).parent / 'fixtures/runtime_baseline'


def stable(value):
    if isinstance(value, dict):
        if 'observation_tick' in value and 'self_status' in value:
            value = project_public_scene(value, schema_version=4)
        return {k: stable(v) for k, v in value.items() if k not in
                ('decision_seconds', 'decision_timing', 'revision', 'python', 'trace',
                 'public_observation_schema_version')}
    if isinstance(value, list): return [stable(v) for v in value]
    return value


class RuntimeIntegrationTests(unittest.TestCase):
    def test_app_and_runner_match_accepted_action_tape(self):
        fixture = json.loads((FIXTURES / 'input_tape.json').read_text())
        requests = {(r['observation_tick'], r['tank_id']): r
                    for row in fixture['actions'] for r in row}
        class TapeBot(BufferedController):
            def request(self, scene):
                return requests.get((scene['observation_tick'], 'tank-2'), keyboard_request(scene, set()))
        clock, window = Clock(), WindowStub()
        world = World(duel=True, round_limit=fixture['round_limit'])
        app = DrivingApp(window, world, scheduler=TapeBot(), clock=clock)
        self.addCleanup(app.close)
        calls = []
        original = MatchRunner.tick
        with patch.object(MatchRunner, 'tick', lambda runner, calls=calls, original=original: (calls.append(1), original(runner))[-1]):
            for row, scene, events in zip(fixture['actions'], fixture['scenes'], fixture['events']):
                request = next((r for r in row if r['tank_id'] == 'tank-1'), None)
                window.held = set()
                window.pressed = set()
                if request:
                    if request['throttle']: window.held.add('w' if request['throttle'] > 0 else 's')
                    if request['turn']: window.held.add('d' if request['turn'] > 0 else 'a')
                    if request['fire']: window.pressed.add('space')
                clock.now += 1/60
                app.update()
                self.assertEqual(project_public_scene(world.observe('tank-1'),schema_version=4), scene)
                self.assertEqual([asdict(e) for e in world.hit_events], events)
        self.assertGreater(len(calls), 0, 'desktop must delegate actual ticks to MatchRunner')

    def test_trace_recorder_preserves_legacy_rows(self):
        for fixture in sorted(FIXTURES.glob('*.jsonl.gz')):
            with self.subTest(fixture=fixture.name), tempfile.TemporaryDirectory() as directory:
                with gzip.open(fixture, 'rt') as stream:
                    expected = [json.loads(line) for line in stream]
                header = expected[0]
                path = Path(directory) / 'new.jsonl.gz'
                calls = []
                original = MatchRunner.tick
                with patch.object(MatchRunner, 'tick', lambda runner, calls=calls, original=original: (calls.append(1), original(runner))[-1]):
                    run_game(header['manifest'], header['condition'], header['assignments'], path)
                self.assertGreater(len(calls), 0, 'evaluation must use MatchRunner')
                with gzip.open(path, 'rt') as stream:
                    actual = [json.loads(line) for line in stream]
                self.assertEqual(stable(actual), stable(expected))

    def test_zero_and_multiple_steps_preserve_fire(self):
        clock, window = Clock(), WindowStub()
        app = DrivingApp(window, World(open_map()), clock=clock)
        self.addCleanup(app.close)
        window.pressed = {'space'}
        app.update()  # Render-only frame.
        self.assertEqual(app.scene['bullets'], [])
        window.pressed.clear()
        clock.now += 3/60
        app.update()
        self.assertEqual(len(app.scene['bullets']), 1)
        self.assertEqual(app.scene['observation_tick'], 3)

    def test_ui_release_barrier_blocks_gameplay(self):
        clock, window = Clock(), WindowStub()
        app = DrivingApp(window, World(open_map()), clock=clock)
        self.addCleanup(app.close)
        app.input.wait_for_release = True
        initial = app.scene['tanks']
        window.pressed, window.held = {'space'}, {'w', 'space'}
        clock.now += 1/60
        app.update()
        self.assertEqual(app.scene['tanks'], initial)
        self.assertFalse(app.scene['bullets'])


    def test_recorder_failure_closes_all_workers(self):
        from tank_game import evaluation
        from tank_game.agents import InlineWorker
        with gzip.open(FIXTURES / 'legacy-0.jsonl.gz', 'rt') as stream:
            header = json.loads(next(stream))
        original_write, original_close = evaluation._write, InlineWorker.close
        closed = []
        def write(stream, row):
            if row['kind'] == 'step': raise OSError('trace write failed')
            original_write(stream, row)
        def close(worker):
            closed.append(worker)
            original_close(worker)
        with (tempfile.TemporaryDirectory() as directory, patch.object(evaluation, '_write', write),
              patch.object(InlineWorker, 'close', close),
              self.assertRaisesRegex(OSError, 'trace write failed')):
            run_game(header['manifest'], header['condition'], header['assignments'], Path(directory) / 'bad.gz')
        self.assertEqual(len(closed), 2)


    def test_smoke_runner_preserves_old_report_and_digest(self):
        from tank_game.baseline import run_baseline
        expected = json.loads((FIXTURES / 'smoke.json').read_text())
        calls = []
        original = MatchRunner.tick
        with patch.object(MatchRunner, 'tick', lambda runner, calls=calls, original=original: (calls.append(1), original(runner))[-1]):
            actual = run_baseline(steps=720)
        self.assertEqual(stable(actual), stable(expected))
        self.assertGreater(len(calls), 0)


    def test_dying_trace_rows_remain_empty_and_do_not_request_another_decision(self):
        from tank_game.entities import BulletState
        from tests.test_duel import duel
        with gzip.open(FIXTURES / 'legacy-0.jsonl.gz', 'rt') as stream:
            header = json.loads(next(stream))
        world = duel()
        world._bullets = (BulletState('incoming', 111, 100, -180, 0, owner_id='tank-2'),)
        with tempfile.TemporaryDirectory() as directory, patch('tank_game.evaluation.setup', return_value=world):
            path = Path(directory) / 'dying.gz'
            report = run_game(header['manifest'], header['condition'], header['assignments'], path)
            with gzip.open(path, 'rt') as stream:
                rows = [json.loads(line) for line in stream if json.loads(line)['kind'] == 'step']
        self.assertTrue(report['hit_events'])
        self.assertGreater(len(rows), 1)
        for row in rows[1:]:
            self.assertEqual(row['actions'], [])
            self.assertNotIn('observations', row)
        self.assertEqual(report['decisions'], {'tank-1': 1, 'tank-2': 1})
