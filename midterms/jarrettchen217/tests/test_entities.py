"""Contracts for immutable, controller-independent simulation records."""

import unittest
from dataclasses import FrozenInstanceError, fields

from tank_game.config import GameConfig
from tank_game.entities import BulletState, TankState


class ConfigTests(unittest.TestCase):
    def test_defaults_supply_the_accepted_simulation_parameters(self):
        config = GameConfig()
        self.assertEqual(
            tuple(getattr(config, name) for name in (
                'tank_radius', 'forward_speed', 'reverse_speed', 'turn_speed_deg',
                'tick_rate', 'bullet_radius', 'bullet_speed', 'bullet_lifetime',
                'fire_interval', 'max_bullets',
            )),
            (8.0, 45.0, 35.0, 180.0, 60, 1.5, 90.0, 10.0, .25, 5),
        )
        with self.assertRaises(FrozenInstanceError):
            config.tick_rate = 30

    def test_config_rejects_nonpositive_nonfinite_and_wrong_numeric_types(self):
        for field in fields(GameConfig):
            invalid = (0, -1, float('nan'), float('inf'), -float('inf'), True, '5', None)
            if field.name in ('tick_rate', 'max_bullets'):
                invalid += (1.5, 60.0)
            for value in invalid:
                with self.subTest(field=field.name, value=value), self.assertRaises(
                    (ValueError, TypeError)
                ):
                    GameConfig(**{field.name: value})

    def test_config_allows_finite_positive_overrides(self):
        config = GameConfig(tank_radius=2, tick_rate=120, max_bullets=1)
        self.assertEqual(config.tank_radius, 2)
        self.assertEqual(config.tick_rate, 120)
        self.assertEqual(config.max_bullets, 1)


class TankStateTests(unittest.TestCase):
    def test_tank_record_is_frozen_and_has_no_controller_slot(self):
        tank = TankState('tank-1', 24, 24, 0)
        self.assertTrue(tank.alive)
        self.assertEqual(tank.radius, 8)
        self.assertEqual(tank.cooldown_remaining, 0)
        with self.assertRaises(FrozenInstanceError):
            tank.x = 99
        with self.assertRaises(TypeError):
            TankState('tank-1', 24, 24, 0, controller=object())

    def test_headings_are_normalized_without_quantization(self):
        for heading, expected in ((-90, 270), (360, 0), (721.5, 1.5), (359.6, 359.6), (-1e-15, 0)):
            with self.subTest(heading=heading):
                self.assertEqual(TankState('tank-1', 24, 24, heading).heading_deg, expected)

    def test_tank_rejects_nonfinite_or_wrong_numeric_types(self):
        for name in ('x', 'y', 'heading_deg', 'radius', 'cooldown_remaining'):
            for value in (float('nan'), float('inf'), -float('inf'), True, '1', None):
                with self.subTest(field=name, value=value):
                    args = {'id': 'tank-1', 'x': 24, 'y': 24, 'heading_deg': 0}
                    args[name] = value
                    with self.assertRaises((ValueError, TypeError)):
                        TankState(**args)

    def test_tank_rejects_invalid_identity_boolean_and_bounds(self):
        for override in ({'id': ''}, {'id': 1}, {'id': True}, {'alive': 1},
                         {'alive': 'yes'}, {'radius': 0}, {'radius': -1},
                         {'cooldown_remaining': -.01}):
            with self.subTest(override=override):
                args = {'id': 'tank-1', 'x': 24, 'y': 24, 'heading_deg': 0}
                args.update(override)
                with self.assertRaises((ValueError, TypeError)):
                    TankState(**args)

    def test_negative_finite_positions_are_valid_without_map_context(self):
        tank = TankState('tank-1', -2, -3, 0, alive=False)
        self.assertEqual((tank.x, tank.y, tank.alive), (-2, -3, False))


class BulletStateTests(unittest.TestCase):
    def test_bullet_retains_hidden_metadata_in_immutable_record(self):
        bullet = BulletState('bullet-1', 24, 24, -90, 0, owner_id='tank-1', age=2)
        self.assertEqual((bullet.radius, bullet.owner_id, bullet.age), (1.5, 'tank-1', 2))
        self.assertEqual(BulletState('bullet-2', 0, 0, 0, 0).owner_id, '')
        with self.assertRaises(FrozenInstanceError):
            bullet.age = 3

    def test_bullet_rejects_nonfinite_or_wrong_numeric_types(self):
        for name in ('x', 'y', 'vx', 'vy', 'radius', 'age'):
            for value in (float('nan'), float('inf'), -float('inf'), True, '1', None):
                with self.subTest(field=name, value=value):
                    args = {'id': 'bullet-1', 'x': 24, 'y': 24, 'vx': 90, 'vy': 0}
                    args[name] = value
                    with self.assertRaises((ValueError, TypeError)):
                        BulletState(**args)

    def test_bullet_rejects_invalid_identity_owner_and_bounds(self):
        for override in ({'id': ''}, {'id': 1}, {'owner_id': 1}, {'owner_id': True},
                         {'radius': 0}, {'radius': -1}, {'age': -.01}):
            with self.subTest(override=override):
                args = {'id': 'bullet-1', 'x': 24, 'y': 24, 'vx': 90, 'vy': 0}
                args.update(override)
                with self.assertRaises((ValueError, TypeError)):
                    BulletState(**args)


if __name__ == '__main__':
    unittest.main()
