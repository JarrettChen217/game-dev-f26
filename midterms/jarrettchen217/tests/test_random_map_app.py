"""Real input routing and round state, with only the window/process replaced."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tank_game.agents import AgentScheduler, InlineWorker
from tank_game.app import DrivingApp
from tank_game.keymap import DEFAULT_KEYMAP_PATH, KeymapError, load_keymap
from tank_game.strategies import make_policy
from tests.test_driving_app import WindowStub


class RandomAppTests(unittest.TestCase):
    def make_app(self):
        from tank_game.random_rounds import RandomRoundSession
        window = WindowStub()
        window.KEY_N = 'n'
        session = RandomRoundSession(17, round_limit=1/60)
        app = DrivingApp(window, random_session=session, strategy='hard', clock=window.clock,
                         scheduler_factory=lambda: AgentScheduler(InlineWorker(make_policy('hard'))))
        self.addCleanup(app.close)
        return window, app, session

    def test_next_map_rebuilds_bot_and_releases_keys_before_playing(self):
        window, app, session = self.make_app()
        old, policy = session.record, app.scheduler.worker.policy
        window.pressed = {'n'}  # ignored during play
        app.update()
        self.assertEqual(session.record, old)
        window.held = {'n', 'w', 'space'}
        app.update()
        self.assertNotEqual(session.record.layout_id, old.layout_id)
        self.assertIsNot(app.scheduler.worker.policy, policy)
        self.assertEqual(app.scene['observation_tick'], 0)
        window.pressed.clear()
        app.update()
        self.assertEqual(app.scene['bullets'], [])
        self.assertEqual(app.scene['tanks'][0]['x'], 16)

    def test_removed_space_shortcut_does_not_override_next_map(self):
        window, app, session = self.make_app()
        app.update()
        old = session.record
        window.pressed = {'n', 'space'}
        app.update()
        self.assertNotEqual(session.record.layout_id, old.layout_id)
        self.assertEqual(app.scene['round_id'], 2)

    def test_random_hud_contains_seed_and_both_end_actions(self):
        window, app, _ = self.make_app()
        texts = []
        window.text = lambda x, y, s, color: texts.append(s)
        window.pget = lambda x, y: 7
        for name in ('cls', 'rect', 'rectb', 'circ', 'circb', 'line', 'tri', 'pset'):
            setattr(window, name, lambda *args: None)
        app.update()
        app.draw()
        rendered = ' '.join(texts)
        self.assertIn('SEED:17', rendered.upper())
        self.assertIn('NEXT MAP', rendered)
        self.assertIn('Retry same map', rendered)
        self.assertNotIn('SPACE:', rendered)

    def test_legacy_keymap_only_enforces_new_conflicts_in_random_mode(self):
        data = json.loads(DEFAULT_KEYMAP_PATH.read_text())
        data['bindings'].pop('next_map', None)
        data['bindings']['quit'] = ['N']
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'keys.json'
            path.write_text(json.dumps(data))
            self.assertEqual(load_keymap(path).names('quit'), ('N',))
            with self.assertRaises(KeymapError):
                load_keymap(path, enable_next_map=True)

    def test_cli_inspection_has_host_seed_but_no_private_controller_metadata(self):
        result = subprocess.run([sys.executable, '-m', 'tank_game', '--duel', '--random-map',
                                 '--map-seed', '17', '--inspect'], capture_output=True,
                                text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('SEED:17', result.stdout)
        for args in (['--random-map'], ['--duel', '--map-seed', '1'],
                     ['--duel', '--random-map', '--map-seed', '-1']):
            bad = subprocess.run([sys.executable, '-m', 'tank_game', *args],
                                 capture_output=True, text=True, check=False)
            self.assertNotEqual(bad.returncode, 0)
