"""Duel extensions must not turn one hit into two deaths or allow body tunneling."""

import math
import unittest
from dataclasses import replace

from tank_game.config import GameConfig
from tank_game.controllers import keyboard_request
from tank_game.entities import BulletState
from tank_game.map import Spawn
from tank_game.world import World
from tests.test_driving import open_map


def duel(a=None, b=None, **kw):
    a = a or Spawn(100, 100, 0)
    b = b or Spawn(180, 100, 180)
    return World(open_map(a), duel=True, spawns=(a, b), **kw)


def action(world, tank_id, throttle=0, turn=0, fire=False):
    scene = world.observe(tank_id)
    req = keyboard_request(scene, set(), fire_pressed=fire)
    req.update(throttle=throttle, turn=turn)
    world.submit_action(tank_id, req)


class DuelTests(unittest.TestCase):
    def test_default_duel_has_two_clear_reachable_spawns(self):
        w = World(duel=True)
        scene = w.observe('tank-1')
        self.assertEqual(len(scene['tanks']), 2)
        a, b = scene['tanks']
        self.assertGreater(math.hypot(a['x']-b['x'], a['y']-b['y']), 16)
        self.assertEqual(scene['duel']['result'], None)

    def test_single_hit_only_kills_target_and_survivor_wins(self):
        w = duel()
        w._bullets = (BulletState('hit', 111, 100, -180, 0),)
        w.step()
        self.assertFalse(w.observe('tank-1')['self_status']['alive'])
        self.assertTrue(w.observe('tank-2')['self_status']['alive'])
        self.assertEqual(w.observe('tank-1')['duel']['result'], 'tank-2')
        self.assertEqual(len(w.observe('tank-1')['effects']), 1)

    def test_simultaneous_hits_draw_and_show_two_explosions(self):
        snapshots = []
        for reverse in (False, True):
            w = duel()
            w._bullets = (BulletState('a', 111, 100, -180, 0),
                          BulletState('b', 169, 100, 180, 0))
            if reverse:
                w._bullets = w._bullets[::-1]
                w._tanks = dict(reversed(list(w._tanks.items())))
            w.step()
            s = w.observe('tank-1')
            self.assertEqual(s['duel']['result'], 'draw')
            self.assertEqual(s['tanks'], [])
            self.assertEqual(len(s['effects']), 2)
            snapshots.append(s)
        self.assertEqual(snapshots[0], snapshots[1])

    def test_head_on_high_speed_and_stationary_contact_are_order_independent(self):
        for moving_second in (False, True):
            endpoints = []
            for reverse in (False, True):
                w = duel(config=GameConfig(forward_speed=6000))
                if reverse:
                    w._tanks = dict(reversed(list(w._tanks.items())))
                action(w, 'tank-1', throttle=1)
                if moving_second:
                    action(w, 'tank-2', throttle=1)
                w.step()
                a, b = w._tanks['tank-1'], w._tanks['tank-2']
                self.assertGreaterEqual(math.hypot(a.x-b.x, a.y-b.y), 16-1e-7)
                self.assertLess(a.x, b.x)
                endpoints.append((a, b))
            self.assertEqual(endpoints[0], endpoints[1])

    def test_touching_tanks_can_separate_and_turn(self):
        w = duel(b=Spawn(116, 100, 180))
        action(w, 'tank-1', throttle=-1, turn=1)
        w.step()
        self.assertLess(w._tanks['tank-1'].x, 100)
        self.assertEqual(w._tanks['tank-1'].heading_deg, 3)

    def test_crossing_paths_stop_before_body_overlap(self):
        w = duel(a=Spawn(100, 140, 0), b=Spawn(140, 100, 90),
                 config=GameConfig(forward_speed=4800))
        action(w, 'tank-1', throttle=1)
        action(w, 'tank-2', throttle=1)
        w.step()
        a, b = w._tanks.values()
        self.assertGreaterEqual(math.hypot(a.x-b.x, a.y-b.y), 16-1e-7)
        self.assertLess(a.x, 140)
        self.assertLess(b.y, 140)

    def test_timeout_freezes_and_restart_restores_both_spawns(self):
        w = duel(round_limit=2/60)
        w.step()
        w.step()
        self.assertEqual(w.observe('tank-1')['duel']['result'], 'draw')
        self.assertEqual(w.observe('tank-1')['round_status'], 'GAME_OVER')
        before = w.observe('tank-1')
        w.step()
        self.assertEqual(w.observe('tank-1'), before)
        self.assertTrue(w.restart())
        s = w.observe('tank-2')
        self.assertEqual(s['round_id'], 2)
        self.assertEqual(s['duel']['elapsed'], 0)
        self.assertEqual(len(s['tanks']), 2)

    def test_illegal_overlapping_or_disconnected_spawns_are_rejected(self):
        for b in (Spawn(108, 100, 0), Spawn(2, 100, 0)):
            with self.assertRaises(ValueError):
                duel(b=b)
        from tank_game.map import WallEdge
        m = open_map()
        m = replace(m, edges=m.edges + tuple(WallEdge('vertical', 4, y)
                                            for y in range(10)))
        with self.assertRaises(ValueError):
            World(m, duel=True, spawns=(m.spawn, Spawn(180, 100, 0)))

    def test_hit_at_timeout_boundary_precedes_draw(self):
        w = duel(round_limit=1/60)
        w._bullets = (BulletState('edge', 112.5, 100, -180, 0),)
        w.step()
        self.assertEqual(w.observe('tank-1')['duel']['result'], 'tank-2')

    def test_simultaneous_newborn_shots_use_both_targets_before_result(self):
        w = duel(b=Spawn(124, 100, 180), config=GameConfig(bullet_speed=600))
        action(w, 'tank-1', fire=True)
        action(w, 'tank-2', fire=True)
        w.step()
        self.assertEqual(w.observe('tank-1')['duel']['result'], 'draw')
        self.assertEqual(len(w.observe('tank-1')['effects']), 2)

    def test_wall_adjacent_contact_never_pushes_either_body_into_wall(self):
        w = duel(a=Spawn(20, 20, 180), b=Spawn(40, 20, 180),
                 config=GameConfig(forward_speed=3000))
        for _ in range(8):
            action(w, 'tank-1', throttle=1)
            action(w, 'tank-2', throttle=1)
            w.step()
            a, b = w._tanks['tank-1'], w._tanks['tank-2']
            self.assertGreaterEqual(a.x, 10-1e-7)
            self.assertGreaterEqual(b.x-a.x, 16-1e-7)
