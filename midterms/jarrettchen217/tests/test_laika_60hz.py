"""Real native-source backend contracts; no substitute policy or physics."""
import platform
import subprocess
import sys
import unittest
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]/'tank_game/laika_60hz/engine.dylib'


@unittest.skipUnless(sys.platform == 'darwin' and platform.machine() == 'arm64',
                     'optional source60Hz artifact currently targets macOS arm64')
class Source60Tests(unittest.TestCase):
    def world(self):
        self.assertTrue(LIB.is_file(), 'the60Hz source backend must be built')
        from tank_game.laika_60hz.world import World60
        world = World60(1000)
        self.addCleanup(world.close)
        return world

    def test_sixty_actual_world_and_laika_steps_have_one_second_public_time(self):
        world = self.world()
        for _ in range(60):
            world.step()
        scene = world.observe('tank-1')
        self.assertEqual(scene['rules_profile'], 'laika-source-60hz-v1')
        self.assertEqual(scene['rules']['tick_rate'], 60)
        self.assertEqual(scene['rules']['settlement_frames'], 180)
        self.assertEqual(scene['observation_tick'], 60)
        self.assertEqual(scene['duel']['elapsed'], 1.)
        self.assertEqual(world.diagnostics['world_steps'], 60)
        self.assertEqual(world.diagnostics['laika_calls'], 60)
        facts = world.presentation_facts()
        self.assertEqual(facts['source_seats'], {'tank-1': 1, 'tank-2': 0})
        self.assertEqual(scene['round_phase'], 'active')
        self.assertEqual(facts['settlement'], {'remaining_seconds': 0., 'total_seconds': 3.})

    def test_real_actions_restart_validation_and_resource_close(self):
        world = self.world()
        original = world.raw_render
        scene = world.observe('tank-1')
        request = {'round_id': 1, 'observation_tick': 0, 'source_id': 'tank-1',
                   'throttle': 1, 'turn': 0, 'fire': True}
        from tank_game.controllers import keyboard_request
        request = keyboard_request(scene, set())
        request.update(throttle=1, turn=0, fire=True)
        world.submit_action('tank-1', request)
        world.step()
        self.assertNotEqual(world.raw_render, original)
        self.assertEqual(len(world.observe('tank-1')['bullets']), 1)
        self.assertGreater(world.observe('tank-1')['bullets'][0]['remaining_lifetime'], 9.9)
        world.submit_action('tank-2', request)
        self.assertEqual(world.rejected_actions, 1)
        self.assertTrue(world.restart(allow_active=True))
        self.assertEqual(world.raw_render, original)
        self.assertEqual(world.observe('tank-1')['round_id'], 2)
        world.close();world.close()
        with self.assertRaises(RuntimeError):
            world.step()

    def test_cli_names_the_adaptation_explicitly(self):
        self.assertTrue(LIB.is_file(), 'the60Hz source backend must be built')
        run = subprocess.run([sys.executable, '-m', 'tank_game', '--duel', '--strategy',
                              'laika', '--rules-profile', 'laika-60hz', '--inspect'],
                             capture_output=True, text=True, timeout=10, check=False)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn('"rules_profile": "laika-source-60hz-v1"', run.stdout)
        self.assertIn('"tick_rate": 60', run.stdout)

    def test_hud_facts_are_host_only_and_follow_the_actual_engine_counter(self):
        world = self.world()
        self.assertNotIn('settlement', world.observe('tank-1'))
        for _ in range(1200):
            world.step()
            if world.observe('tank-1')['round_phase'] == 'settling':
                break
        self.assertEqual(world.presentation_facts()['settlement']['remaining_seconds'], 3.)
        world.step()
        self.assertAlmostEqual(world.presentation_facts()['settlement']['remaining_seconds'], 179/60)
        for _ in range(179):
            world.step()
        facts = world.presentation_facts()
        self.assertEqual(facts['round_phase'], 'frozen')
        self.assertEqual(facts['settlement']['remaining_seconds'], 0.)
        self.assertEqual(facts['result'], 'tank-2')


if __name__ == '__main__':
    unittest.main()
