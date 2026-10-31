"""World-level safety/replay checks with explicit, adjustable test fixtures."""

import math
import random
import unittest

from tank_game.config import GameConfig
from tank_game.controllers import keyboard_request
from tank_game.entities import BulletState
from tank_game.map import GameMap, Spawn, WallEdge
from tank_game.world import World


def arena(heading=0):
    # 128 x 128 box split by a continuous vertical wall at x=64.
    edges = tuple([WallEdge('horizontal', x, y) for y in (0, 4) for x in range(4)]
                  + [WallEdge('vertical', x, y) for x in (0, 4) for y in range(4)]
                  + [WallEdge('vertical', 2, y) for y in range(4)])
    return GameMap(4, 4, edges, tile_size=32, wall_thickness=2,
                   spawn=Spawn(32, 32, heading))


def advance(world, keys=(), fire=False):
    request = keyboard_request(world.observe('tank-1'), set(keys))
    request['fire'] = fire
    world.submit_action('tank-1', request)
    world.step()


def assert_body_clear(test, body, game_map, context):
    # Independent oracle: closest point on a solid rectangle, not physics helpers
    # or the rounded public observation (which can round into a contact).
    test.assertTrue(all(math.isfinite(value) for value in (body.x, body.y)), context)
    test.assertGreaterEqual(body.x, body.radius - 1e-6, context)
    test.assertGreaterEqual(body.y, body.radius - 1e-6, context)
    test.assertLessEqual(body.x, game_map.width - body.radius + 1e-6, context)
    test.assertLessEqual(body.y, game_map.height - body.radius + 1e-6, context)
    for wall in game_map.walls:
        nearest_x = max(wall.x, min(body.x, wall.x + wall.width))
        nearest_y = max(wall.y, min(body.y, wall.y + wall.height))
        test.assertGreaterEqual(math.hypot(body.x - nearest_x, body.y - nearest_y),
                                body.radius - 1e-6, f'{context}, wall={wall}')


class WorldRegressionTests(unittest.TestCase):
    def test_forward_and_reverse_cannot_cross_internal_wall_over_repeated_ticks(self):
        for radius in (3, 8, 12):
            for heading, keys in ((0, {'w'}), (180, {'s'})):
                with self.subTest(radius=radius, heading=heading):
                    game_map = arena(heading)
                    config = GameConfig(tank_radius=radius, forward_speed=12000,
                                        reverse_speed=12000, tick_rate=30)
                    world = World(game_map, config)
                    for tick in range(20):
                        advance(world, keys)
                        tank = world._tanks['tank-1']
                        assert_body_clear(self, tank, game_map, f'tick={tick}')
                        self.assertAlmostEqual(tank.x, 63 - radius, places=5)
                    # Holding into contact must not prevent later moving away.
                    advance(world, {'s'} if heading == 0 else {'w'})
                    self.assertLess(world._tanks['tank-1'].x, 63 - radius - 1)
                    assert_body_clear(self, world._tanks['tank-1'], game_map, 'back away')

    def test_high_speed_bullets_reflect_without_crossing_dividing_wall(self):
        game_map = arena()
        config = GameConfig(tank_radius=8, bullet_radius=1.5, bullet_speed=6000,
                            tick_rate=60, bullet_lifetime=3)
        world = World(game_map, config)
        # Off-axis fixture isolates wall safety from legitimate self-hits.
        world._bullets = (BulletState('fast', 41.5 + 2e-7, 16, 6000, 0),)
        advance(world)
        self.assertEqual(len(world._bullets), 1)
        bullet = world._bullets[0]
        # 100 units this tick, enough to cross the thin wall if sweeps are lost.
        # Legal center interval [3.5, 61.5], launch at 41.5 + tiny safety gap.
        self.assertAlmostEqual(bullet.x, 25.5, places=5)
        self.assertEqual(bullet.vx, 6000)
        for tick in range(100):
            advance(world)
            self.assertEqual(len(world._bullets), 1)
            bullet = world._bullets[0]
            assert_body_clear(self, bullet, game_map, f'bullet tick={tick}')
            self.assertLessEqual(bullet.x, 61.5 + 1e-6)
            self.assertAlmostEqual(math.hypot(bullet.vx, bullet.vy), 6000, places=6)
        self.assertEqual(world.projectile_limit_hits, 0)

    def test_projectile_contact_limit_stops_safely_and_does_not_extend_lifetime(self):
        game_map = arena()
        world = World(game_map, GameConfig(tank_radius=8, bullet_radius=1.5,
                      bullet_speed=1_000_000, tick_rate=60, bullet_lifetime=.05))
        world._bullets = (BulletState('capped', 41.5 + 2e-7, 16, 1_000_000, 0),)
        advance(world)
        self.assertEqual(world.projectile_limit_hits, 1)
        self.assertEqual(len(world._bullets), 1)
        assert_body_clear(self, world._bullets[0], game_map, 'capped projectile')
        advance(world)
        self.assertEqual(world.projectile_limit_hits, 2)
        assert_body_clear(self, world._bullets[0], game_map, 'second capped tick')
        advance(world)
        self.assertEqual(world._bullets, ())
        self.assertTrue(world.observe('tank-1')['self_status']['active_bullets'] == 0)

    def test_seeded_driving_and_shooting_stays_legal_and_replays_exactly(self):
        for seed, tick_rate, radius, speed in ((1203, 30, 3, 300), (13, 60, 8, 45),
                                               (84, 120, 12, 1200)):
            with self.subTest(seed=seed, tick_rate=tick_rate):
                game_map = arena()
                config = GameConfig(tank_radius=radius, forward_speed=speed,
                                    reverse_speed=speed / 2, turn_speed_deg=270,
                                    tick_rate=tick_rate, bullet_speed=800,
                                    bullet_radius=1.5, bullet_lifetime=.75,
                                    fire_interval=.1, max_bullets=5)
                worlds = [World(game_map, config), World(game_map, config)]
                rng = random.Random(seed)
                fired = False
                playing_steps = 0
                restarts = 0
                bullet_checks = 0
                for tick in range(600):
                    # Continue real physics after self-hit rather than spending
                    # almost all the seeded replay in a frozen terminal state.
                    if worlds[0].observe('tank-1')['round_status'] == 'GAME_OVER':
                        for world in worlds:
                            self.assertTrue(world.restart())
                        restarts += 1
                    if worlds[0].observe('tank-1')['round_status'] == 'PLAYING':
                        playing_steps += 1
                    keys = rng.choice(((), ('w',), ('s',), ('w', 'a'), ('w', 'd'),
                                       ('s', 'a'), ('s', 'd'), ('a',), ('d',)))
                    fire = tick % 11 == 0
                    for world in worlds:
                        advance(world, keys, fire)
                    context = f'seed={seed}, tick={tick}, keys={keys}, fire={fire}'
                    self.assertEqual(worlds[0].observe('tank-1'),
                                     worlds[1].observe('tank-1'), context)
                    self.assertEqual(worlds[0]._tanks, worlds[1]._tanks, context)
                    self.assertEqual(worlds[0]._bullets, worlds[1]._bullets, context)
                    tank = worlds[0]._tanks['tank-1']
                    assert_body_clear(self, tank, game_map, context)
                    self.assertLessEqual(tank.x, 63 - radius + 1e-6, context)
                    self.assertTrue(0 <= tank.heading_deg < 360, context)
                    self.assertLessEqual(len(worlds[0]._bullets), config.max_bullets, context)
                    for bullet in worlds[0]._bullets:
                        fired = True
                        bullet_checks += 1
                        assert_body_clear(self, bullet, game_map, context)
                        self.assertLessEqual(bullet.x, 63 - bullet.radius + 1e-6, context)
                        self.assertAlmostEqual(math.hypot(bullet.vx, bullet.vy),
                                               config.bullet_speed, places=6)
                        self.assertLess(bullet.age, config.bullet_lifetime)
                self.assertTrue(fired, 'Replay must exercise actual projectiles')
                self.assertGreaterEqual(playing_steps, tick_rate,
                                        'Replay must exercise at least one second of live physics')
                self.assertGreaterEqual(restarts, 2, 'Replay must span multiple round resets')
                self.assertGreaterEqual(bullet_checks, 10,
                                        'Replay must repeatedly check real projectile geometry')
                self.assertEqual(worlds[0].collision_limit_hits, 0)
                self.assertEqual(worlds[0].projectile_limit_hits, 0)
