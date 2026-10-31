"""Approved public timers reflect the authoritative clock, never a UI clock."""
import unittest
from dataclasses import replace

from tank_game.config import GameConfig
from tank_game.controllers import BufferedController
from tank_game.entities import BulletState
from tank_game.runner import MatchRunner
from tank_game.world import World
from tests.test_driving import open_map
from tests.test_round_lifecycle import finish
from tests.test_shooting import request


class PublicTimingTests(unittest.TestCase):
    def test_exact_own_cooldown_and_all_bullet_lifetimes_are_detached(self):
        world = World(duel=True)
        world._tanks['tank-1'] = replace(world._tanks['tank-1'], cooldown_remaining=.125)
        world._tanks['tank-2'] = replace(world._tanks['tank-2'], cooldown_remaining=.2)
        world._bullets = (BulletState('bullet-1', 40, 40, 90, 0,
                                      owner_id='tank-2', age=3.25),)
        one, two = world.observe('tank-1'), world.observe('tank-2')
        self.assertIn('cooldown_remaining', one['self_status'])
        self.assertIn('remaining_lifetime', one['bullets'][0])
        self.assertEqual(one['self_status']['cooldown_remaining'], .125)
        self.assertEqual(two['self_status']['cooldown_remaining'], .2)
        self.assertEqual(one['bullets'][0]['remaining_lifetime'], 6.75)
        self.assertEqual(one['bullets'], two['bullets'])
        self.assertNotIn('cooldown_remaining', one['tanks'][1])
        self.assertNotIn('owner_id', one['bullets'][0])
        self.assertNotIn('age', one['bullets'][0])
        one['self_status']['cooldown_remaining'] = 100
        one['bullets'][0]['remaining_lifetime'] = 100
        self.assertEqual(world.observe('tank-1')['bullets'][0]['remaining_lifetime'], 6.75)
        self.assertEqual(world.observe('tank-1')['self_status']['cooldown_remaining'], .125)

    def test_newborn_timers_include_the_firing_tick(self):
        world = World(open_map())
        request(world, fire=True)
        scene = world.observe('tank-1')
        self.assertIn('remaining_lifetime', scene['bullets'][0])
        self.assertAlmostEqual(scene['bullets'][0]['remaining_lifetime'], 10-1/60)
        self.assertAlmostEqual(scene['self_status']['cooldown_remaining'], .25-1/60)
        self.assertFalse(scene['self_status']['can_fire'])

    def test_pause_does_not_decrement_public_timers(self):
        world = World(open_map())
        request(world, fire=True)
        before = world.observe('tank-1')
        self.assertIn('cooldown_remaining', before['self_status'])
        MatchRunner(world, {'tank-1': BufferedController()}).pause()
        self.assertEqual(world.observe('tank-1'), before)

    def test_expiry_removes_row_and_restart_clears_timers(self):
        world = World(open_map(), GameConfig(bullet_lifetime=2/60))
        request(world, fire=True)
        first = world.observe('tank-1')
        self.assertIn('remaining_lifetime', first['bullets'][0])
        self.assertAlmostEqual(first['bullets'][0]['remaining_lifetime'], 1/60)
        world.step()
        self.assertEqual(world.observe('tank-1')['bullets'], [])
        world.restart(allow_active=True)
        scene = world.observe('tank-1')
        self.assertEqual(scene['round_id'], 2)
        self.assertEqual(scene['self_status']['cooldown_remaining'], 0)
        self.assertTrue(scene['self_status']['can_fire'])

    def test_death_freezes_surviving_projectile_at_actual_hit_time(self):
        world = World(open_map())
        world._bullets = (BulletState('incoming',111,100,-180,0),
                          BulletState('survivor',200,200,90,0,age=3.25))
        world.step()
        scene = world.observe('tank-1')
        self.assertEqual(scene['round_status'], 'DYING')
        self.assertIn('remaining_lifetime', scene['bullets'][0])
        # Contact after travelling1.5 units at180/s, not the full1/60 tick.
        self.assertAlmostEqual(scene['bullets'][0]['remaining_lifetime'], 6.75-1/120)
        finish(world)
        self.assertEqual(world.observe('tank-1')['bullets'], scene['bullets'])
        self.assertEqual(world.observe('tank-1')['round_status'], 'GAME_OVER')


if __name__ == '__main__':
    unittest.main()
