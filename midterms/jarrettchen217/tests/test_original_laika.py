"""Unchanged original engine through the Simulator boundary, not a new bot."""
import hashlib
import json
import math
import shutil
import subprocess
import unittest
from pathlib import Path

from tank_game.controllers import keyboard_request

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT/'tank_game/original_laika'


@unittest.skipUnless(shutil.which('node'), 'optional original profile requires existing Node')
class OriginalLaikaTests(unittest.TestCase):
    def world(self, seed=1000):
        from tank_game.original_laika.world import OriginalWorld
        world = OriginalWorld(seed=seed)
        self.addCleanup(world.close)
        return world

    def test_identical_actions_match_direct_original_exports_frame_for_frame(self):
        actions = [[(i//9) % 3-1, (i//5) % 3-1, i % 11 == 0] for i in range(90)]
        for seed in (1,17,1000):
            with self.subTest(seed=seed):
                self.compare_exports(seed,actions)

    def compare_exports(self, seed, actions):
        expected = json.loads(subprocess.run(
            [shutil.which('node'), str(ROOT/'tests/fixtures/original_laika_oracle.mjs'),
             str(ASSETS/'engine.wasm'), str(seed)], input=json.dumps(actions),
            text=True, capture_output=True, check=True, timeout=15).stdout)
        world = self.world(seed)
        try:
            self.assertEqual(list(world.raw_render), expected[0])
            for index, (throttle, turn, fire) in enumerate(actions[:len(expected)-1]):
                scene = world.observe('tank-1')
                request = keyboard_request(scene, set())
                request.update(throttle=throttle, turn=turn, fire=fire)
                if scene['self_status']['alive']:
                    world.submit_action('tank-1', request)
                world.step()
                self.assertEqual(list(world.raw_render), expected[index+1], f'frame{index+1}')
            return world.observe('tank-1')
        finally:
            world.close()

    def test_whole_round_including_settlement_matches_the_original(self):
        scene = self.compare_exports(1000,[[0,0,False]]*1000)
        self.assertEqual(scene['round_status'], 'GAME_OVER')

    def test_profile_reports_actual_source_rules_and_human_seat(self):
        world = self.world()
        scene = world.observe('tank-1')
        self.assertEqual(scene['rules_profile'], 'laika-original-v1')
        self.assertEqual(scene['rules']['tick_rate'], 25)
        self.assertEqual(scene['rules']['turn_speed_deg'], 250)
        self.assertEqual(scene['rules']['bullet_collision'], 'point')
        self.assertEqual(scene['rules']['tank_collision'], 'hull-and-barrel-union')
        self.assertEqual(scene['controller_roles'], {'tank-1': 'external', 'tank-2': 'original-laika'})
        raw = world.raw_render
        offset = 138+int(raw[5])*4+6  # Original seat1 is our human tank1.
        tank = next(t for t in scene['tanks'] if t['id'] == 'tank-1')
        self.assertEqual((tank['x'], tank['y'], tank['heading_deg']),
                         (raw[offset], raw[offset+1], (raw[offset+2]-90) % 360))
        self.assertAlmostEqual(scene['rules']['forward_speed'], 2*raw[2])
        self.assertAlmostEqual(scene['rules']['bullet_speed'], 2.25*raw[2])

    def test_bot_moves_and_fires_without_a_python_policy_or_scheduler(self):
        world = self.world()
        first = world.observe('tank-2')['tanks'][1]
        moved = fired = False
        for _ in range(350):
            world.step()
            scene = world.observe('tank-2')
            bot = next((t for t in scene['tanks'] if t['id'] == 'tank-2'), None)
            moved |= bot is not None and (bot['x'], bot['y']) != (first['x'], first['y'])
            fired |= scene['self_status']['active_bullets'] > 0
            if scene['round_status'] == 'GAME_OVER':
                break
        self.assertTrue(moved)
        self.assertTrue(fired)

    def test_projectile_status_uses_actual_point_bullet_units_and_lifetime(self):
        world = self.world()
        seen = False
        for _ in range(350):
            world.step()
            scene = world.observe('tank-1')
            for bullet in scene['bullets']:
                seen = True
                self.assertEqual(bullet['radius'], 0)
                self.assertAlmostEqual(math.hypot(bullet['vx'],bullet['vy']),
                                       scene['rules']['bullet_speed'], delta=.001)
                self.assertGreater(bullet['remaining_lifetime'], 0)
                self.assertLessEqual(bullet['remaining_lifetime'], 10)
            if seen:
                break
        self.assertTrue(seen)

    def test_child_exit_is_a_visible_error_and_close_still_reaps_it(self):
        from tank_game.original_laika.bridge import OriginalEngineError
        world = self.world()
        world.process.kill()
        world.process.wait(timeout=2)
        with self.assertRaises(OriginalEngineError):
            world.step()
        world.close()
        self.assertIsNotNone(world.process.poll())

    def test_rejects_stale_duplicate_and_internal_bot_override(self):
        world = self.world()
        scene = world.observe('tank-1')
        request = keyboard_request(scene, set())
        world.submit_action('tank-1', request)
        world.submit_action('tank-1', request)
        world.submit_action('tank-2', keyboard_request(world.observe('tank-2'), set()))
        world.step()
        world.submit_action('tank-1', request)
        self.assertEqual(world.rejected_actions, 3)

    def test_restart_is_explicit_and_exact_and_close_is_idempotent(self):
        world = self.world()
        initial = world.raw_render
        world.step()
        current = world.raw_render
        self.assertFalse(world.restart())
        self.assertEqual(world.raw_render, current)
        self.assertTrue(world.restart(allow_active=True))
        self.assertEqual(world.raw_render, initial)
        self.assertEqual(world.observe('tank-1')['round_id'], 2)
        process = world.process
        world.close()
        world.close()
        self.assertIsNotNone(process.poll())

    def test_settlement_keeps_running_until_original_freeze(self):
        world = self.world()
        saw_settlement = False
        for _ in range(1000):
            world.step()
            scene = world.observe('tank-1')
            if sum(t['alive'] for t in scene['all_tanks']) < 2 and not world.raw_render[14]:
                saw_settlement = True
                self.assertEqual(scene['round_status'], 'PLAYING')
            if world.raw_render[14]:
                self.assertEqual(scene['round_status'], 'GAME_OVER')
                break
        self.assertTrue(saw_settlement)
        self.assertEqual(world.observe('tank-1')['round_status'], 'GAME_OVER')

    def test_artifact_bytes_match_the_pinned_original(self):
        manifest = json.loads((ASSETS/'manifest.json').read_text())
        self.assertEqual(hashlib.sha256((ASSETS/'engine.wasm').read_bytes()).hexdigest(),
                         manifest['wasm_sha256'])
        for name,source in manifest['source_files'].items():
            self.assertEqual(hashlib.sha256((ASSETS/'source'/name).read_bytes()).hexdigest(),
                             source['sha256'])
