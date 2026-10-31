"""Permanent S1.4 CI cases for timed path boundaries and successive rounds."""

import tempfile
import unittest
from dataclasses import replace

from tank_game.app import DrivingApp
from tank_game.config import GameConfig
from tank_game.entities import BulletState
from tank_game.map import GameMap, Rect, Spawn, WallEdge
from tank_game.paths import Segment, first_hit
from tank_game.physics import move_circle, ricochet_circle
from tank_game.world import World
from tests.test_driving import open_map
from tests.test_driving_app import WindowStub, confirm_result
from tests.test_interfaces import payload
from tests.test_keymap import defaults, write_config
from tests.test_round_lifecycle import finish, hit_world
from tests.test_shooting import request


class TimedPathRegressionTests(unittest.TestCase):
    def test_reflected_leg_hits_target_not_on_start_end_chord(self):
        flight = ricochet_circle(10, 10, 1, 40, 0, 1, (Rect(20, 0, 1, 40),))
        target = (Segment(0, 1, 15, 10, 15, 10),)
        # First contact is x=14, 4/40 seconds; end is left of the launch point.
        self.assertLess(flight.x, 10)
        hit = first_hit(flight.path, target, 1)
        self.assertIsNotNone(hit, 'Returning path must contact the target')
        self.assertAlmostEqual(hit, .1, places=7)

    def test_sliding_path_does_not_hit_target_on_start_end_chord(self):
        motion = move_circle(10, 10, 1, 20, 20, (Rect(20, 0, 1, 40),))
        target = (Segment(0, 1, 14.5, 20, 14.5, 20),)
        # Actual legs run diagonally to (19,19), then vertically to (19,30).
        # A shortcut from (10,10) to (19,30) would incorrectly cross this target.
        self.assertAlmostEqual(motion.x, 19, places=5)
        self.assertAlmostEqual(motion.y, 30, places=5)
        self.assertIsNone(first_hit(motion.path, target, .5))

    def test_world_detects_hit_on_return_leg_within_one_fast_step(self):
        maze = open_map()
        maze = GameMap(10, 10, maze.edges + tuple(
            WallEdge('vertical', 4, y) for y in range(10)), spawn=maze.spawn)
        world = World(maze)
        world._bullets = (BulletState('returning', 120, 100, 2000, 0),)
        world.step()
        self.assertFalse(world.observe('tank-1')['self_status']['alive'])
        self.assertEqual(world.observe('tank-1')['round_status'], 'DYING')
        self.assertEqual(world._bullets, ())

    def test_tangent_moving_contact_is_not_missed(self):
        world = World(open_map())
        # Combined radius 9.5; bullet grazes the tank at (100, 90.5).
        world._bullets = (BulletState('tangent', 95, 90.5, 600, 0),)
        world.step()
        self.assertFalse(world.observe('tank-1')['self_status']['alive'])

    def test_lifetime_endpoint_is_exclusive_but_just_before_it_can_hit(self):
        for lifetime, expected_alive in ((.01, True), (.010001, False)):
            with self.subTest(lifetime=lifetime):
                world = World(open_map(), GameConfig(bullet_lifetime=lifetime))
                # Distance to contact is 1.5 units; 150 units/sec gives exactly .01.
                world._bullets = (BulletState('boundary', 111, 100, -150, 0),)
                world.step()
                self.assertEqual(world.observe('tank-1')['self_status']['alive'], expected_alive)
                self.assertEqual(world._bullets, ())

    def test_first_death_freezes_other_bullet_at_actual_contact_time(self):
        world = World(open_map())
        world._bullets = (BulletState('impact', 111, 100, -180, 0),
                          BulletState('background', 80, 60, 120, 0, age=.2))
        world.step()
        bullet, = world._bullets
        # Impact time: 1.5/180 = 1/120 sec, not a full 1/60 frame.
        self.assertEqual(bullet.id, 'background')
        self.assertAlmostEqual(bullet.x, 81)
        self.assertAlmostEqual(bullet.age, .2 + 1 / 120)
        frozen = bullet
        finish(world)
        for _ in range(60):
            world.step()
        self.assertEqual(world._bullets, (frozen,))

    def test_newborn_does_not_hit_reversing_tanks_pre_spawn_path(self):
        world = World(open_map(), GameConfig(reverse_speed=2400))
        request(world, throttle=-1, fire=True)
        # Tank reversed from x100 to x60 before spawning the right-facing bullet.
        # Replaying its old path alongside the newborn would invent a crossing.
        self.assertAlmostEqual(world._tanks['tank-1'].x, 60)
        self.assertTrue(world.observe('tank-1')['self_status']['alive'])
        bullet, = world._bullets
        self.assertAlmostEqual(bullet.x, 71, places=5)
        self.assertAlmostEqual(bullet.age, 1 / 60)


class SuccessiveRoundRegressionTests(unittest.TestCase):
    def test_restart_clears_surviving_projectiles_and_nonzero_cooldown(self):
        world = World(open_map(Spawn(80, 80, 90)),
                      GameConfig(tank_radius=7, bullet_lifetime=2))
        world._tanks['tank-1'] = replace(world._tanks['tank-1'], cooldown_remaining=.2)
        world._bullets = (BulletState('impact', 90, 80, -180, 0),
                          BulletState('background', 40, 40, 120, 0, owner_id='tank-1', age=.4))
        world.step()
        self.assertFalse(world.observe('tank-1')['self_status']['alive'])
        self.assertGreater(world._tanks['tank-1'].cooldown_remaining, 0)
        self.assertEqual(len(world._bullets), 1)
        finish(world)
        self.assertTrue(world.restart())
        scene = world.observe('tank-1')
        self.assertEqual(scene['bullets'], [])
        self.assertEqual(scene['effects'], [])
        self.assertEqual((scene['tanks'][0]['x'], scene['tanks'][0]['y'],
                          scene['tanks'][0]['heading_deg'], scene['tanks'][0]['radius']),
                         (80, 80, 90, 7))
        self.assertEqual(scene['rules']['bullet_lifetime'], 2)
        self.assertTrue(scene['self_status']['can_fire'])
        self.assertEqual(world._tanks['tank-1'].cooldown_remaining, 0)

    def test_repeated_rounds_reject_all_previous_round_actions(self):
        world = World(open_map())
        prior_actions = []
        for round_id in range(1, 7):
            with self.subTest(round_id=round_id):
                scene = world.observe('tank-1')
                self.assertEqual(scene['round_id'], round_id)
                self.assertEqual(scene['observation_tick'], 0)
                current = payload(world, throttle=1, fire=True)
                for old in prior_actions:
                    rejected = world.rejected_actions
                    world.submit_action('tank-1', old)
                    self.assertEqual(world.rejected_actions, rejected + 1)
                world.step()
                self.assertEqual(world._tanks['tank-1'].x, 100)
                self.assertEqual(world._bullets, ())
                prior_actions.append(current)  # tick zero, matching the next round's tick
                world._bullets = (BulletState('incoming', 111, 100, -180, 0),)
                world.step()
                finish(world)
                self.assertTrue(world.restart())

    def test_explosion_duration_uses_configured_simulation_rate(self):
        for hz in (30, 60, 120):
            with self.subTest(hz=hz):
                world = World(open_map(), GameConfig(tick_rate=hz))
                world._bullets = (BulletState('incoming', 111, 100, -180, 0),)
                world.step()
                scene = world.observe('tank-1')
                self.assertEqual(scene['round_status'], 'DYING')
                tick = scene['observation_tick']
                for step in range(1, 44):
                    world.step()
                    scene = world.observe('tank-1')
                    self.assertEqual(scene['observation_tick'], tick)
                    expected = 'DYING' if step / hz < .35 else 'GAME_OVER'
                    self.assertEqual(scene['round_status'], expected)

    def test_legacy_retry_binding_does_not_bypass_menu_or_change_fire(self):
        with tempfile.TemporaryDirectory() as directory:
            config = defaults()
            config['bindings']['restart'] = ['F']
            world = hit_world()
            finish(world)
            window = WindowStub()
            app = DrivingApp(window, world, keymap_path=write_config(directory, config), clock=window.clock)
            window.pressed = {'space'}
            app.update()
            self.assertEqual(app.scene['round_status'], 'GAME_OVER')
            window.pressed = {'f'}
            app.update()
            self.assertEqual(app.scene['round_status'], 'GAME_OVER')
            confirm_result(window, app)
            self.assertEqual(app.scene['round_status'], 'PLAYING')
            self.assertEqual(world._bullets, ())
            window.pressed.clear()
            app.update()  # release gate
            window.pressed = {'f'}
            app.update()
            self.assertEqual(len(world._bullets), 1)
            self.assertEqual(app.scene['round_id'], 2)

    def test_escape_in_each_terminal_state_does_not_advance_world(self):
        for phase in ('DYING', 'GAME_OVER'):
            with self.subTest(phase=phase):
                world = hit_world()
                if phase == 'GAME_OVER':
                    finish(world)
                window = WindowStub()
                app = DrivingApp(window, world, clock=window.clock)
                before = world.observe('tank-1')
                window.pressed = {'esc', 'space', 'f'}
                window.held = {'w', 'd'}
                app.update()
                self.assertFalse(window.exited)
                self.assertEqual(app.ui.screen, 'results' if phase == 'GAME_OVER' else 'pause')
                self.assertEqual(world.observe('tank-1'), before)
