"""Pin the controller/world information and action boundary."""

import json
import subprocess
import sys
import unittest
from dataclasses import replace

from tank_game.actions import Action
from tank_game.entities import BulletState
from tank_game.world import World


def payload(world, **changes):
    scene = world.observe('tank-1')
    data = {'round_id': scene['round_id'], 'observation_tick': scene['observation_tick'],
            'tank_id': 'tank-1', 'throttle': 0, 'turn': 0, 'fire': False}
    data.update(changes)
    return data


class InterfaceTests(unittest.TestCase):
    def test_snapshot_is_detached_at_every_nested_level(self):
        world = World()
        before = world.observe('tank-1')
        scene = world.observe('tank-1')
        scene['tanks'][0]['x'] = 999
        scene['map']['walls'][0]['x'] = 999
        scene['rules']['tank_radius'] = 999
        scene['self_status']['alive'] = False
        scene['bullets'].append({'id': 'invented'})
        self.assertEqual(before, world.observe('tank-1'))
        self.assertEqual(json.loads(json.dumps(before)), before)

    def test_internal_state_and_future_information_are_not_serialized(self):
        world = World()
        world._bullets = (BulletState('bullet-1', 40.4, 41.6, 89.7, -2.4,
                                     owner_id='tank-1', age=3.25),)
        tank = world._tanks['tank-1']
        world._tanks['tank-1'] = replace(tank, cooldown_remaining=1.25)
        before = world.observe('tank-1')
        world._next_bullet_id += 99
        world._rejected_actions += 99
        self.assertEqual(before, world.observe('tank-1'))
        self.assertEqual(set(before), {'schema_version', 'observation_precision',
                         'round_id', 'observation_tick',
                         'self_id', 'map', 'rules', 'tanks', 'bullets',
                         'self_status', 'round_status', 'effects'})
        self.assertEqual(set(before['tanks'][0]), {'id', 'x', 'y', 'heading_deg', 'radius'})
        self.assertEqual(set(before['bullets'][0]),
                         {'id', 'x', 'y', 'vx', 'vy', 'radius', 'remaining_lifetime'})
        self.assertNotIn('owner_id', before['bullets'][0])
        self.assertNotIn('age', before['bullets'][0])
        self.assertEqual(before['bullets'][0]['x'], 40.375)
        self.assertEqual(before['bullets'][0]['y'], 41.625)

    def test_quantization_half_up_and_heading_wrap(self):
        world = World()
        world._tanks['tank-1'] = replace(world._tanks['tank-1'],
                                        x=24.0625, y=25.01, heading_deg=359.875)
        tank = world.observe('tank-1')['tanks'][0]
        self.assertEqual((tank['x'], tank['y'], tank['heading_deg']), (24.125, 25, 0))

    def test_valid_action_and_one_action_budget_each_tick(self):
        world = World()
        request = payload(world, throttle=1, turn=-1, fire=True)
        self.assertEqual(world.submit_action('tank-1', request), Action(1, -1, True))
        self.assertEqual(world.submit_action('tank-1', request), Action())
        self.assertEqual(world.rejected_actions, 1)
        world.step()
        self.assertEqual(world.submit_action('tank-1', payload(world, turn=1)), Action(0, 1))

    def test_invalid_actions_are_noop_not_privileged_mutations(self):
        cases = [None, [], 1, 'fire', {}, {'x': 900},
                 {'throttle': True}, {'turn': 1.0}, {'fire': 1},
                 {'throttle': 2}, {'round_id': True}, {'observation_tick': 0.0},
                 {'tank_id': 'enemy'}, {'round_id': 2}, {'observation_tick': 1},
                 {'x': 99}, {'heading_deg': 120}, {'throttle': float('nan')}]
        for patch in cases:
            with self.subTest(patch=patch):
                world = World()
                before = world.observe('tank-1')
                data = payload(world)
                if isinstance(patch, dict):
                    if not patch:
                        data = patch
                    else:
                        data.update(patch)
                else:
                    data = patch
                self.assertEqual(world.submit_action('tank-1', data), Action())
                self.assertEqual(before, world.observe('tank-1'))
                self.assertEqual(world.rejected_actions, 1)

    def test_wrong_source_stale_round_dead_and_phase_are_rejected(self):
        world = World()
        self.assertEqual(world.submit_action('unknown', payload(world)), Action())
        old = payload(world, throttle=1)
        world.step()
        self.assertEqual(world.submit_action('tank-1', old), Action())
        world._tanks['tank-1'] = replace(world._tanks['tank-1'], alive=False)
        self.assertEqual(world.submit_action('tank-1', payload(world, fire=True)), Action())
        self.assertEqual(world.observe('tank-1')['tanks'], [])
        self.assertFalse(world.observe('tank-1')['self_status']['can_fire'])
        with self.assertRaises(ValueError):
            world.observe('unknown')
        for status in ('DYING', 'GAME_OVER'):
            world = World()
            world._round_status = status
            self.assertEqual(world.submit_action('tank-1', payload(world, turn=1)), Action())

    def test_rejected_request_does_not_consume_valid_budget(self):
        world = World()
        world.submit_action('tank-1', payload(world, x=999))
        self.assertEqual(world.submit_action('tank-1', payload(world, throttle=1)), Action(1))

    def test_driving_step_accepts_detached_controller_and_is_repeatable(self):
        worlds = [World(), World()]
        for tick in range(3):
            for world in worlds:
                scene = world.observe('tank-1')
                request = payload(world, throttle=1, turn=1, fire=True)
                self.assertEqual(scene['observation_tick'], tick)
                world.submit_action('tank-1', request)
                world.step()
        self.assertEqual(worlds[0].observe('tank-1'), worlds[1].observe('tank-1'))
        self.assertGreater(worlds[0].observe('tank-1')['tanks'][0]['x'], 16)
        self.assertEqual(len(worlds[0].observe('tank-1')['bullets']), 1)

    def test_core_import_does_not_load_pyxel(self):
        result = subprocess.run([sys.executable, '-c',
            ('import sys; from tank_game.world import World; '
             'World(); assert "pyxel" not in sys.modules')], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
