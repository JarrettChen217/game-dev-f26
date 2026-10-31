"""Driving uses the existing action boundary and fixed simulation steps."""

import math
import unittest
from dataclasses import replace

from tank_game.config import GameConfig
from tank_game.controllers import keyboard_request
from tank_game.map import GameMap, Spawn, WallEdge
from tank_game.world import World


def open_map(spawn=None):
    spawn = Spawn(100, 100, 0) if spawn is None else spawn
    edges = tuple([WallEdge('horizontal', x, y) for y in (0, 10) for x in range(10)]
                  + [WallEdge('vertical', x, y) for x in (0, 10) for y in range(10)])
    return GameMap(10, 10, edges, spawn=spawn)


def drive(world, keys, count=1):
    for _ in range(count):
        scene = world.observe('tank-1')
        world.submit_action('tank-1', keyboard_request(scene, keys))
        world.step()


class KeyboardTests(unittest.TestCase):
    def test_aliases_and_opposite_keys_cancel(self):
        scene = World().observe('tank-1')
        for keys, axes in (({'w'}, (1, 0)), ({'up'}, (1, 0)), ({'s'}, (-1, 0)),
                           ({'down'}, (-1, 0)), ({'a'}, (0, -1)), ({'left'}, (0, -1)),
                           ({'d'}, (0, 1)), ({'right'}, (0, 1)),
                           ({'w', 'up'}, (1, 0)), ({'w', 'down'}, (0, 0)),
                           ({'a', 'right'}, (0, 0)), ({'w', 'd'}, (1, 1)),
                           ({'f'}, (0, 0)), (set(), (0, 0))):
            with self.subTest(keys=keys):
                request = keyboard_request(scene, keys)
                self.assertEqual((request['throttle'], request['turn']), axes)
                self.assertFalse(request['fire'])

    def test_controller_only_uses_detached_public_identity(self):
        scene = World().observe('tank-1')
        scene.update(round_id=42, observation_tick=103, self_id='another-tank')
        before = dict(scene)
        request = keyboard_request(scene, {'w'})
        self.assertEqual(set(request), {'round_id', 'observation_tick', 'tank_id',
                                       'throttle', 'turn', 'fire'})
        self.assertEqual((request['round_id'], request['observation_tick'], request['tank_id']),
                         (42, 103, 'another-tank'))
        self.assertEqual(scene, before)


class DrivingTests(unittest.TestCase):
    def test_forward_reverse_rates_and_idle_stop(self):
        world = World(open_map())
        drive(world, {'w'}, 60)
        self.assertAlmostEqual(world._tanks['tank-1'].x, 145)
        drive(world, {'s'}, 60)
        self.assertAlmostEqual(world._tanks['tank-1'].x, 110)
        before = world._tanks['tank-1']
        world.step()
        self.assertEqual(before, world._tanks['tank-1'])

    def test_turning_in_place_wraps_and_reverse_follows_heading(self):
        world = World(open_map())
        drive(world, {'a'})
        self.assertEqual(world._tanks['tank-1'].heading_deg, 357)
        drive(world, {'d'}, 31)
        self.assertEqual(world._tanks['tank-1'].heading_deg, 90)
        drive(world, {'s'}, 60)
        self.assertAlmostEqual(world._tanks['tank-1'].x, 100)
        self.assertAlmostEqual(world._tanks['tank-1'].y, 65)

    def test_simultaneous_input_turns_before_translation(self):
        world = World(open_map())
        drive(world, {'w', 'd'})
        tank = world._tanks['tank-1']
        self.assertEqual(tank.heading_deg, 3)
        self.assertAlmostEqual(tank.x, 100 + .75 * math.cos(math.radians(3)))
        self.assertAlmostEqual(tank.y, 100 + .75 * math.sin(math.radians(3)))

    def test_configured_rates_use_fixed_time_not_render_time(self):
        world = World(open_map(), GameConfig(tick_rate=30, forward_speed=60,
                                            reverse_speed=15, turn_speed_deg=90))
        drive(world, {'w'}, 30)
        self.assertAlmostEqual(world._tanks['tank-1'].x, 160)
        drive(world, {'d'}, 30)
        self.assertEqual(world._tanks['tank-1'].heading_deg, 90)
        drive(world, {'s'}, 30)
        self.assertAlmostEqual(world._tanks['tank-1'].y, 85)

    def test_repeated_actions_match_and_aliases_share_physics(self):
        worlds = [World(), World()]
        for _ in range(300):
            drive(worlds[0], {'w', 'd'})
            drive(worlds[1], {'up', 'right'})
        self.assertEqual(worlds[0].observe('tank-1'), worlds[1].observe('tank-1'))
        self.assertEqual(worlds[0]._tanks, worlds[1]._tanks)

    def test_invalid_and_stale_requests_cannot_move_and_dead_world_stays_still(self):
        world = World(open_map())
        before = world._tanks['tank-1']
        bad = keyboard_request(world.observe('tank-1'), {'w'})
        bad['x'] = 999
        world.submit_action('tank-1', bad)
        world.step()
        self.assertEqual(before, world._tanks['tank-1'])
        world.submit_action('tank-1', keyboard_request(
            {**world.observe('tank-1'), 'observation_tick': 0}, {'w'}))
        world.step()
        self.assertEqual(before, world._tanks['tank-1'])
        for status in ('DYING', 'GAME_OVER'):
            world._round_status = status
            drive(world, {'w', 'd'})
            self.assertEqual(before, world._tanks['tank-1'])
        world._round_status = 'PLAYING'
        world._tanks['tank-1'] = replace(before, alive=False)
        drive(world, {'w', 'd'})
        self.assertEqual(world._tanks['tank-1'], replace(before, alive=False))

    def test_high_speed_world_stops_before_thin_internal_wall(self):
        world = World(config=GameConfig(forward_speed=6000))
        drive(world, {'w'})
        self.assertAlmostEqual(world._tanks['tank-1'].x, 55, places=5)
        self.assertEqual(world._tanks['tank-1'].y, 16)


if __name__ == '__main__':
    unittest.main()
