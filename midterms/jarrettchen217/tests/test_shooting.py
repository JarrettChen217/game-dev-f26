"""Shared fire requests obey muzzle geometry, capacity and simulation time."""

import math
import unittest
from dataclasses import replace

from tank_game.app import DrivingApp
from tank_game.config import GameConfig
from tank_game.controllers import keyboard_request
from tank_game.entities import BulletState
from tank_game.map import Spawn
from tank_game.world import World
from tests.test_driving import open_map
from tests.test_driving_app import WindowStub


def request(world, fire=False, throttle=0, turn=0):
    scene = world.observe('tank-1')
    action = keyboard_request(scene, set())
    action.update(fire=fire, throttle=throttle, turn=turn)
    world.submit_action('tank-1', action)
    world.step()


class ShootingTests(unittest.TestCase):
    def test_safe_spawn_uses_post_drive_pose_and_flight_speed(self):
        world = World(open_map())
        request(world, True, 1, 1)
        tank = world._tanks['tank-1']
        self.assertEqual(len(world._bullets), 1)
        bullet = world._bullets[0]
        self.assertEqual(bullet.owner_id, tank.id)
        self.assertAlmostEqual(math.degrees(math.atan2(bullet.vy, bullet.vx)), 3)
        self.assertAlmostEqual(math.hypot(bullet.vx, bullet.vy), 90)
        self.assertGreater(math.hypot(bullet.x - tank.x, bullet.y - tank.y), 9.5)
        self.assertAlmostEqual(bullet.age, 1 / 60)

    def test_cooldown_boundary_no_buffer_and_unique_ids(self):
        world = World(open_map())
        request(world, True)
        first = world._bullets[0].id
        for _ in range(14):
            request(world, True)
            self.assertEqual(len(world._bullets), 1)
        self.assertTrue(world.observe('tank-1')['self_status']['can_fire'])
        request(world)
        self.assertEqual(len(world._bullets), 1)  # rejected shots were not queued
        request(world, True)
        self.assertNotEqual(world._bullets[1].id, first)

    def test_capacity_expiry_releases_slot_and_owner_counts_are_separate(self):
        world = World(open_map(), GameConfig(max_bullets=1, bullet_lifetime=.3))
        request(world, True)
        for _ in range(14):
            request(world)
        self.assertFalse(world.observe('tank-1')['self_status']['can_fire'])
        request(world, True)
        self.assertEqual(len(world._bullets), 1)
        for _ in range(2):
            request(world)
        self.assertEqual(world._bullets, ())
        self.assertTrue(world.observe('tank-1')['self_status']['can_fire'])
        request(world, True)
        self.assertEqual(len(world._bullets), 1)
        world._bullets = (replace(world._bullets[0], owner_id='other-tank'),)
        world._tanks['tank-1'] = replace(world._tanks['tank-1'], cooldown_remaining=0)
        request(world, True)
        self.assertEqual(world.observe('tank-1')['self_status']['active_bullets'], 1)

    def test_blocked_muzzle_does_not_start_cooldown_or_consume_capacity(self):
        world = World()
        world._tanks['tank-1'] = replace(world._tanks['tank-1'], x=54.9, y=16)
        request(world, True)
        self.assertEqual(world._bullets, ())
        self.assertEqual(world._tanks['tank-1'].cooldown_remaining, 0)
        self.assertTrue(world.observe('tank-1')['self_status']['can_fire'])
        # Ready is cooldown/capacity only; geometry is checked on the actual request.
        world._tanks['tank-1'] = replace(world._tanks['tank-1'], heading_deg=180)
        request(world, True)
        self.assertEqual(len(world._bullets), 1)

    def test_spawn_cannot_skip_thin_wall_with_large_projectile(self):
        world = World(open_map(Spawn(16, 16, 180)), GameConfig(bullet_radius=20))
        request(world, True)
        self.assertEqual(world._bullets, ())
        self.assertEqual(world._tanks['tank-1'].cooldown_remaining, 0)

    def test_invalid_stale_duplicate_dead_or_finished_fire_is_ignored(self):
        world = World(open_map())
        scene = world.observe('tank-1')
        action = keyboard_request(scene, set())
        action.update(fire=True, x=999)
        world.submit_action('tank-1', action)
        world.step()
        self.assertEqual(world._bullets, ())
        action.pop('x')
        world.submit_action('tank-1', action)  # stale
        world.step()
        self.assertEqual(world._bullets, ())
        scene = world.observe('tank-1')
        idle = keyboard_request(scene, set())
        world.submit_action('tank-1', idle)
        world.submit_action('tank-1', {**idle, 'fire': True})
        world.step()
        self.assertEqual(world._bullets, ())
        for status in ('DYING', 'GAME_OVER'):
            world._round_status = status
            request(world, True)
            self.assertEqual(world._bullets, ())
        world._round_status = 'PLAYING'
        world._tanks['tank-1'] = replace(world._tanks['tank-1'], alive=False)
        request(world, True)
        self.assertEqual(world._bullets, ())

    def test_lifetime_boundary_and_bounces_do_not_refresh_age(self):
        world = World(open_map(Spawn(280, 100, 0)), GameConfig(bullet_lifetime=1))
        request(world, True)
        # Isolate expiry from the newly enabled return-hit rule.
        world._tanks['tank-1'] = replace(world._tanks['tank-1'], y=132)
        for _ in range(58):
            request(world)
        self.assertEqual(len(world._bullets), 1)
        self.assertLess(world._bullets[0].vx, 0)  # reflected at internal wall
        self.assertAlmostEqual(world._bullets[0].age, 59 / 60)
        request(world)
        self.assertEqual(world._bullets, ())

    def test_fractional_lifetime_expiry_and_non_default_tick_rate(self):
        for hz in (30, 120):
            world = World(open_map(), GameConfig(tick_rate=hz, bullet_lifetime=.251))
            request(world, True)
            while world._tick / hz < .251:
                self.assertLess(world._bullets[0].age, .251)
                request(world)
            self.assertEqual(world._bullets, ())
        world = World(open_map(), GameConfig(bullet_lifetime=.001))
        request(world, True)
        self.assertEqual(world._bullets, ())
        self.assertFalse(world.observe('tank-1')['self_status']['can_fire'])

    def test_public_boundary_exposes_timers_but_keeps_owner_and_raw_age_hidden(self):
        world = World(open_map())
        request(world, True)
        scene = world.observe('tank-1')
        self.assertEqual(set(scene['bullets'][0]),
                         {'id', 'x', 'y', 'vx', 'vy', 'radius', 'remaining_lifetime'})
        self.assertEqual(set(scene['self_status']),
                         {'alive', 'active_bullets', 'can_fire', 'cooldown_remaining'})
        self.assertEqual(scene['self_status']['active_bullets'], 1)
        self.assertFalse(scene['self_status']['can_fire'])
        scene['bullets'][0]['x'] = -999
        self.assertGreater(world._bullets[0].x, 0)

    def test_repeated_requests_match_and_host_cap_diagnostic_is_private(self):
        worlds = [World(), World()]
        for step in range(180):
            for world in worlds:
                request(world, step % 20 == 0, 1, 1)
        self.assertEqual(worlds[0].observe('tank-1'), worlds[1].observe('tank-1'))
        self.assertEqual(worlds[0]._bullets, worlds[1]._bullets)
        world = World(open_map(), GameConfig(bullet_speed=10000000))
        # A parallel lane exercises the cap without killing the stationary tank.
        world._bullets = (BulletState('capped', 100, 80, 10000000, 0),)
        request(world)
        self.assertGreater(world.projectile_limit_hits, 0)
        self.assertNotIn('projectile_limit_hits', world.observe('tank-1'))

    def test_tangent_spawn_circle_is_rejected(self):
        world = World(open_map())
        # Full-circle check, not just center/heading path: upper wall is y=0..2.
        world._tanks['tank-1'] = replace(world._tanks['tank-1'], y=10.1, heading_deg=300)
        request(world, True)
        self.assertEqual(world._bullets, ())


class FireInputTests(unittest.TestCase):
    def test_adapter_fire_is_an_explicit_press_not_a_held_key(self):
        scene = World().observe('tank-1')
        self.assertFalse(keyboard_request(scene, {'f'})['fire'])
        self.assertTrue(keyboard_request(scene, {'w'}, fire_pressed=True)['fire'])

    def test_window_f_press_fires_once_and_hold_does_not_repeat(self):
        window = WindowStub()
        window.KEY_F = 'f'
        app = DrivingApp(window, World(open_map()), clock=window.clock)
        window.held = {'f'}
        window.pressed = {'f'}
        app.update()
        self.assertEqual(len(app.world._bullets), 1)
        window.pressed.clear()
        for _ in range(30):
            app.update()
        self.assertEqual(len(app.world._bullets), 1)
        window.pressed = {'f'}
        app.update()
        self.assertEqual(len(app.world._bullets), 2)
