"""Ricochets conserve speed and cannot tunnel through thin wall unions."""

import math
import random
import unittest

from tank_game.map import Rect
from tank_game.physics import MAX_CONTACTS, ricochet_circle


class RicochetTests(unittest.TestCase):
    def test_free_travel_and_axis_faces(self):
        free = ricochet_circle(10, 10, 1, 20, -5, .5, ())
        self.assertEqual((free.x, free.y, free.vx, free.vy), (20, 7.5, 20, -5))
        for wall, velocity, expected in (
                (Rect(20, 0, 1, 40), (20, 0), (18, 10, -20, 0)),
                (Rect(0, 20, 40, 1), (0, 20), (10, 18, 0, -20)),
                (Rect(0, 0, 1, 40), (-20, 0), (4, 10, 20, 0)),
                (Rect(0, 0, 40, 1), (0, -20), (10, 4, 0, 20))):
            with self.subTest(wall=wall):
                result = ricochet_circle(10, 10, 1, *velocity, .5, (wall,))
                for actual, target in zip((result.x, result.y, result.vx, result.vy), expected):
                    self.assertAlmostEqual(actual, target, places=5)
                self.assertFalse(result.exhausted)

    def test_high_speed_and_multiple_bounces(self):
        walls = (Rect(0, 0, 1, 30), Rect(20, 0, 1, 30))
        result = ricochet_circle(10, 10, 1, 100, 0, 1, walls)
        self.assertAlmostEqual(result.x, 8, places=4)
        self.assertEqual(result.vx, 100)
        self.assertFalse(result.exhausted)
        result = ricochet_circle(10, 10, 1, 100000, 0, 1, walls)
        self.assertTrue(result.exhausted)
        self.assertGreaterEqual(result.x, 2 - 1e-6)
        self.assertLessEqual(result.x, 19 + 1e-6)
        self.assertLessEqual(result.contacts, MAX_CONTACTS)

    def test_perpendicular_corner_is_simultaneous_and_order_independent(self):
        walls = (Rect(20, 0, 1, 40), Rect(0, 20, 40, 1))
        forward = ricochet_circle(10, 10, 1, 20, 20, .5, walls)
        reverse = ricochet_circle(10, 10, 1, 20, 20, .5, walls[::-1])
        self.assertEqual(forward, reverse)
        self.assertAlmostEqual(forward.x, 18, places=5)
        self.assertAlmostEqual(forward.y, 18, places=5)
        self.assertEqual((forward.vx, forward.vy), (-20, -20))

    def test_connected_segments_match_unsplit_wall(self):
        split = (Rect(20, 0, 1, 20), Rect(20, 20, 1, 20))
        merged = (Rect(20, 0, 1, 40),)
        a = ricochet_circle(10, 20, 1, 20, 0, 1, split)
        b = ricochet_circle(10, 20, 1, 20, 0, 1, merged)
        self.assertEqual(a, b)

    def test_oblique_near_seam_matches_solid_union(self):
        split = (Rect(20, 0, 1, 20), Rect(20, 20, 1, 20))
        merged = (Rect(20, 0, 1, 40),)
        for offset in (0, 1e-6, 1e-5, 1e-4, -1e-4):
            with self.subTest(offset=offset):
                a = ricochet_circle(10, 17.75 + offset, 1, 20, 5, 1, split)
                b = ricochet_circle(10, 17.75 + offset, 1, 20, 5, 1, merged)
                self.assertEqual(a, b)
                self.assertEqual(a, ricochet_circle(10, 17.75 + offset, 1, 20, 5, 1,
                                                   split[::-1]))

    def test_rounded_endpoint_reflects_about_surface_normal(self):
        result = ricochet_circle(16, 16, 2, 10, 10, .5, (Rect(20, 20, 2, 20),))
        self.assertAlmostEqual(result.vx, -10)
        self.assertAlmostEqual(result.vy, -10)
        self.assertAlmostEqual(math.hypot(result.vx, result.vy), math.sqrt(200))
        self.assertLess(result.x, 20 - math.sqrt(2))

    def test_zero_time_and_outward_surface_do_not_bounce(self):
        wall = (Rect(20, 0, 1, 40),)
        result = ricochet_circle(19, 10, 1, -20, 0, .1, wall)
        self.assertEqual((result.x, result.vx, result.contacts), (17, -20, 0))
        result = ricochet_circle(19, 10, 1, 20, 0, 0, wall)
        self.assertEqual((result.x, result.vx, result.contacts), (19, 20, 0))

    def test_seeded_repeated_bounces_remain_clear_and_conserve_speed(self):
        walls = (Rect(0, 0, 1, 100), Rect(99, 0, 1, 100),
                 Rect(0, 0, 100, 1), Rect(0, 99, 100, 1), Rect(45, 25, 2, 50))
        randomizer = random.Random(13)
        for _ in range(12):
            x, y = 20., 20.
            angle = randomizer.random() * math.tau
            vx, vy = 800 * math.cos(angle), 800 * math.sin(angle)
            for _ in range(100):
                result = ricochet_circle(x, y, 1.5, vx, vy, 1 / 60, walls)
                x, y, vx, vy = result.x, result.y, result.vx, result.vy
                self.assertFalse(result.exhausted)
                self.assertAlmostEqual(math.hypot(vx, vy), 800, places=7)
                for wall in walls:
                    cx = max(wall.x, min(x, wall.x + wall.width))
                    cy = max(wall.y, min(y, wall.y + wall.height))
                    self.assertGreaterEqual(math.hypot(x - cx, y - cy), 1.5 - 1e-6)
