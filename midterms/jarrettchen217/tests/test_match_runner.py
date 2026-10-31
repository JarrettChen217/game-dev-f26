"""A match ticks once with detached pre-step views and optional trace output."""
import json
import unittest
from pathlib import Path

from tank_game.controllers import BufferedController
from tank_game.observation_compat import project_public_scene
from tank_game.world import World


class Spy(BufferedController):
    def __init__(self, seen, *, mutate=False):
        super().__init__()
        self.seen = seen
        self.mutate = mutate
        self.calls = 0

    def request(self, scene):
        self.calls += 1
        self.seen.append((scene['self_id'], scene['observation_tick'], scene['rules']['tick_rate']))
        if self.mutate:
            scene['rules']['tick_rate'] = 1
            scene['map']['walls'].clear()
        return super().request(scene)


class Recorder:
    def __init__(self):
        self.rows = []
    def begin_tick(self, tick, phase): self.rows.append(('begin', tick, phase))
    def before_request(self, tid, scene): self.rows.append(('before', tid))
    def after_request(self, tid, scene, request, *, submitted):
        self.rows.append(('after', tid, submitted))
    def end_tick(self): self.rows.append(('end',))


class MatchRunnerTests(unittest.TestCase):
    def test_all_requests_use_same_pre_step(self):
        from tank_game.runner import MatchRunner
        world = World(duel=True)
        seen = []
        bindings = {'tank-2': Spy(seen), 'tank-1': Spy(seen, mutate=True)}
        runner = MatchRunner(world, bindings)
        bindings.clear()
        runner.tick()
        self.assertEqual(seen, [('tank-2', 0, 60), ('tank-1', 0, 60)])
        self.assertEqual(world.observe('tank-1')['observation_tick'], 1)
        self.assertEqual(world.observe('tank-1')['rules']['tick_rate'], 60)
        self.assertTrue(world.observe('tank-1')['map']['walls'])
        with self.assertRaises(ValueError):
            MatchRunner(world, {'missing-tank': Spy([])})

    def test_observation_mutation_cannot_change_other_controller(self):
        from tank_game.runner import MatchRunner
        seen = []
        MatchRunner(World(duel=True), {'tank-1': Spy(seen, mutate=True),
                                     'tank-2': Spy(seen)}).tick()
        self.assertEqual(seen[-1], ('tank-2', 0, 60))

    def test_recorder_does_not_repeat_request_or_fire(self):
        from tank_game.runner import MatchRunner
        fixture = json.loads((Path(__file__).parent / 'fixtures/runtime_baseline/input_tape.json').read_text())
        for enabled in (False, True):
            world = World(duel=True, round_limit=fixture['round_limit'])
            class Tape:
                def __init__(self, tid): self.tid, self.calls = tid, 0
                def request(self, scene):
                    row = fixture['actions'][self.calls]
                    self.calls += 1
                    return next((r for r in row if r['tank_id'] == self.tid), {})
                def pause(self, scene): pass
                def close(self): raise AssertionError('runner cannot close borrowed controller')
            controllers = {tid: Tape(tid) for tid in ('tank-1', 'tank-2')}
            recorder = Recorder() if enabled else None
            runner = MatchRunner(world, controllers, recorder=recorder)
            for expected in fixture['scenes']:
                runner.tick()
                self.assertEqual(project_public_scene(world.observe('tank-1'),schema_version=4), expected)
            self.assertEqual([c.calls for c in controllers.values()], [110, 110])
            if enabled:
                self.assertEqual(sum(row[0] == 'end' for row in recorder.rows), 110)
            before = world.observe('tank-1')
            runner.pause()
            self.assertEqual(world.observe('tank-1'), before)

    def test_nonplaying_requests_drain_without_submission_and_invalid_requests_rejected(self):
        from tank_game.runner import MatchRunner
        world = World(duel=True, round_limit=1/60)
        class Invalid(Spy):
            def request(self, scene):
                super().request(scene)
                return {}
        spy = Invalid([])
        recorder = Recorder()
        runner = MatchRunner(world, {'tank-1': spy}, recorder=recorder)
        runner.tick()
        self.assertEqual(world.rejected_actions, 1)
        runner.tick()
        self.assertEqual(spy.calls, 2)
        self.assertEqual(world.rejected_actions, 1)
        self.assertIn(('after', 'tank-1', False), recorder.rows)


    def test_controller_cannot_suppress_submission_by_mutating_its_view(self):
        from tank_game.controllers import keyboard_request
        from tank_game.runner import MatchRunner
        world = World()
        initial = world.observe('tank-1')['tanks']
        class Mutator(BufferedController):
            def request(self, scene):
                request = keyboard_request(scene, {'forward'})
                scene['round_status'] = 'DYING'
                return request
        MatchRunner(world, {'tank-1': Mutator()}).tick()
        self.assertNotEqual(world.observe('tank-1')['tanks'], initial)
