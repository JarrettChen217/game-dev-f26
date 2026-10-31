"""Real world regressions for timed hits, round freeze and state-scoped input."""

import unittest

from tank_game.app import DrivingApp
from tank_game.config import GameConfig
from tank_game.entities import BulletState
from tank_game.map import GameMap, Spawn, WallEdge
from tank_game.world import World
from tests.test_driving import open_map
from tests.test_driving_app import WindowStub, confirm_result
from tests.test_interfaces import payload
from tests.test_shooting import request


def hit_world():
    world = World(open_map())
    world._bullets = (BulletState('incoming', 111, 100, -180, 0),)
    world.step()
    return world


def finish(world):
    for _ in range(21):
        world.step()


class RoundLifecycleTests(unittest.TestCase):
    def test_hit_stops_at_contact_and_removes_only_impacting_bullet(self):
        world = hit_world()
        scene = world.observe('tank-1')
        self.assertFalse(scene['self_status']['alive'])
        self.assertEqual(scene['round_status'], 'DYING')
        self.assertEqual(scene['tanks'], [])
        self.assertEqual(scene['bullets'], [])
        self.assertFalse(scene['self_status']['can_fire'])
        self.assertEqual(scene['effects'][0]['x'], 100)
        self.assertEqual(scene['effects'][0]['y'], 100)

    def test_fast_moving_crossing_detects_contact_before_both_endpoints(self):
        world = World(open_map(), GameConfig(forward_speed=2400))
        world._bullets = (BulletState('crossing', 120, 80, 0, 2400),)
        request(world, throttle=1)
        self.assertFalse(world.observe('tank-1')['self_status']['alive'])
        # Relative circles meet before their centres reach (120,100).
        self.assertGreater(world._tanks['tank-1'].x, 100)
        self.assertLess(world._tanks['tank-1'].x, 120)

    def test_wall_blocks_hit_even_when_unobstructed_ray_would_cross_tank(self):
        maze = open_map(Spawn(100, 100, 0))
        maze = GameMap(10, 10, maze.edges + tuple(
            WallEdge('vertical', 4, y) for y in range(10)), spawn=maze.spawn)
        world = World(maze)
        world._bullets = (BulletState('blocked', 145, 100, -3000, 0),)
        world.step()
        self.assertTrue(world.observe('tank-1')['self_status']['alive'])
        self.assertGreater(world._bullets[0].x, 128)

    def test_returning_owner_projectile_kills_without_bounce_immunity(self):
        world = World(open_map())
        request(world, fire=True)
        self.assertTrue(world.observe('tank-1')['self_status']['alive'])
        for _ in range(310):
            world.step()
        self.assertFalse(world.observe('tank-1')['self_status']['alive'])
        self.assertEqual(world.observe('tank-1')['round_status'], 'GAME_OVER')

    def test_unbounced_projectile_and_unowned_projectile_use_same_hit_rule(self):
        for owner in ('tank-1', '', 'other'):
            world = World(open_map())
            world._bullets = (BulletState('incoming', 111, 100, -180, 0, owner_id=owner),)
            world.step()
            self.assertFalse(world.observe('tank-1')['self_status']['alive'])

    def test_expired_bullet_cannot_hit_later_in_the_step(self):
        world = World(open_map(), GameConfig(bullet_lifetime=.001))
        world._bullets = (BulletState('expiring', 111, 100, -180, 0),)
        world.step()
        self.assertTrue(world.observe('tank-1')['self_status']['alive'])
        self.assertEqual(world._bullets, ())

    def test_earliest_hit_does_not_depend_on_projectile_order(self):
        bullets = (BulletState('late', 115, 100, -600, 0),
                   BulletState('early', 111, 100, -600, 0))
        snapshots = []
        for ordered in (bullets, bullets[::-1]):
            world = World(open_map())
            world._bullets = ordered
            request(world, throttle=1, fire=True)
            self.assertFalse(world.observe('tank-1')['self_status']['alive'])
            self.assertEqual(len(world._bullets), 1)
            self.assertEqual(world._bullets[0].id, 'late')
            snapshots.append(world.observe('tank-1'))
        self.assertEqual(snapshots[0], snapshots[1])

    def test_death_freezes_background_and_only_explosion_timer_advances(self):
        world = hit_world()
        tank, bullets = dict(world._tanks), world._bullets
        tick = world.observe('tank-1')['observation_tick']
        for index in range(21):
            world.submit_action('tank-1', payload(world, throttle=1, turn=1, fire=True))
            world.step()
            self.assertEqual(world._tanks, tank)
            self.assertEqual(world._bullets, bullets)
            self.assertEqual(world.observe('tank-1')['observation_tick'], tick)
            self.assertEqual(world.observe('tank-1')['round_status'],
                             'DYING' if index < 20 else 'GAME_OVER')
        before = world.observe('tank-1')
        for _ in range(60):
            world.step()
        self.assertEqual(world.observe('tank-1'), before)

    def test_restart_clears_every_round_transient_and_rejects_old_action(self):
        world = hit_world()
        old = payload(world, throttle=1, fire=True)
        finish(world)
        self.assertTrue(getattr(world, 'restart', lambda: False)())
        scene = world.observe('tank-1')
        self.assertEqual(scene['round_id'], 2)
        self.assertEqual(scene['observation_tick'], 0)
        self.assertEqual(scene['round_status'], 'PLAYING')
        self.assertEqual(scene['effects'], [])
        self.assertEqual(scene['bullets'], [])
        self.assertEqual(scene['tanks'][0]['x'], 100)
        self.assertEqual(world._tanks['tank-1'].cooldown_remaining, 0)
        world.submit_action('tank-1', old)
        world.step()
        self.assertEqual(world._tanks['tank-1'].x, 100)
        self.assertEqual(world._bullets, ())
        request(world, throttle=1, fire=True)
        self.assertGreater(world._tanks['tank-1'].x, 100)
        self.assertEqual(len(world._bullets), 1)

    def test_app_ignores_gameplay_during_dying_and_game_over(self):
        window = WindowStub()
        world = hit_world()
        app = DrivingApp(window, world, clock=window.clock)
        window.held = {'w', 'd'}
        window.pressed = {'space', 'f'}
        before = dict(world._tanks)
        app.update()  # Space during explosion cannot restart.
        self.assertEqual(world._tanks, before)
        self.assertEqual(app.scene['round_status'], 'DYING')
        self.assertEqual(world.rejected_actions, 0)  # input never submitted
        window.pressed = {'f'}
        for _ in range(30):
            app.update()
        self.assertEqual(app.scene['round_status'], 'GAME_OVER')
        self.assertEqual(world._tanks, before)
        self.assertEqual(world.rejected_actions, 0)

    def test_enter_release_restart_requires_old_game_keys_to_release(self):
        window = WindowStub()
        world = hit_world()
        finish(world)
        app = DrivingApp(window, world, clock=window.clock)
        window.held = {'space', 'w', 'd'}
        confirm_result(window, app)
        self.assertEqual(app.scene['round_status'], 'PLAYING')
        self.assertEqual(app.scene['observation_tick'], 0)
        self.assertEqual(app.scene['round_id'], 2)
        self.assertEqual(world._bullets, ())
        window.pressed.clear()
        for _ in range(20):
            app.update()
        self.assertEqual(world._tanks['tank-1'].x, 100)
        self.assertEqual(world._tanks['tank-1'].heading_deg, 0)
        self.assertEqual(world._bullets, ())
        window.held.clear()
        app.update()
        window.held = {'w'}
        window.pressed = {'space'}
        app.update()
        self.assertGreater(world._tanks['tank-1'].x, 100)
        self.assertEqual(len(world._bullets), 1)

    def test_restart_is_not_a_competitive_action_or_active_round_shortcut(self):
        world = World(open_map())
        before = world.observe('tank-1')
        self.assertFalse(getattr(world, 'restart', lambda: True)())
        self.assertEqual(before, world.observe('tank-1'))
        world.submit_action('tank-1', payload(world, restart=True))
        self.assertEqual(world.rejected_actions, 1)

    def test_inactive_next_map_key_does_not_block_fixed_map_restart_release(self):
        window = WindowStub()
        world = hit_world()
        finish(world)
        app = DrivingApp(window, world, clock=window.clock)
        confirm_result(window, app)
        window.pressed.clear()
        window.held = {'n'}
        app.update()  # N has no postgame function in fixed-map mode.
        window.held = {'n', 'w'}
        app.update()
        self.assertGreater(world._tanks['tank-1'].x, 100)

    def test_effect_snapshot_is_detached(self):
        world = hit_world()
        scene = world.observe('tank-1')
        self.assertTrue('effects' in scene)
        scene['effects'][0]['x'] = 999
        self.assertEqual(world.observe('tank-1')['effects'][0]['x'], 100)
