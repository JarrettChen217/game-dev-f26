"""Swept circular bodies must slide, respect corners, and ignore wall seams."""

import math
import random
import unittest

from tank_game.map import Rect, fixed_map
from tank_game.physics import move_circle


def assert_clear(test, result, radius, walls):
    for wall in walls:
        px = max(wall.x, min(result.x, wall.x + wall.width))
        py = max(wall.y, min(result.y, wall.y + wall.height))
        test.assertGreaterEqual(math.hypot(result.x - px, result.y - py), radius - 1e-7)


class CollisionTests(unittest.TestCase):
    def test_free_motion_and_idle_are_exact(self):
        result = move_circle(10, 20, 8, 30, -12, ())
        self.assertEqual((result.x, result.y, result.exhausted), (40, 8, False))
        result = move_circle(10, 20, 8, 0, 0, (Rect(30, 0, 2, 100),))
        self.assertEqual((result.x, result.y), (10, 20))

    def test_sweep_stops_on_faces_even_when_endpoint_is_beyond_wall(self):
        for wall, start, delta, expected in (
                (Rect(32, 0, 2, 100), (10, 20), (100, 0), (24, 20)),
                (Rect(32, 0, 2, 100), (60, 20), (-100, 0), (42, 20)),
                (Rect(0, 32, 100, 2), (20, 10), (0, 100), (20, 24)),
                (Rect(0, 32, 100, 2), (20, 60), (0, -100), (20, 42))):
            with self.subTest(wall=wall, start=start):
                result = move_circle(*start, 8, *delta, (wall,))
                self.assertAlmostEqual(result.x, expected[0], places=5)
                self.assertAlmostEqual(result.y, expected[1], places=5)
                assert_clear(self, result, 8, (wall,))

    def test_diagonal_approach_preserves_wall_tangent_motion(self):
        wall = Rect(32, 0, 2, 100)
        result = move_circle(10, 20, 8, 30, 30, (wall,))
        self.assertAlmostEqual(result.x, 24, places=5)
        self.assertAlmostEqual(result.y, 50, places=5)
        assert_clear(self, result, 8, (wall,))

    def test_touching_body_can_move_away_and_along_wall_without_jitter(self):
        walls = (Rect(32, 0, 2, 300),)
        result = move_circle(24, 20, 8, -3, 0, walls)
        self.assertEqual((result.x, result.y), (21, 20))
        x, y = 24, 20
        for _ in range(200):
            result = move_circle(x, y, 8, 1, .75, walls)
            x, y = result.x, result.y
            assert_clear(self, result, 8, walls)
        self.assertAlmostEqual(x, 24, places=5)
        self.assertAlmostEqual(y, 170, places=5)

    def test_simultaneous_inside_corner_is_order_independent(self):
        walls = (Rect(32, 0, 2, 100), Rect(0, 32, 100, 2))
        results = [move_circle(16, 16, 8, 100, 100, order)
                   for order in (walls, walls[::-1])]
        self.assertEqual(results[0], results[1])
        self.assertAlmostEqual(results[0].x, 24, places=5)
        self.assertAlmostEqual(results[0].y, 24, places=5)
        assert_clear(self, results[0], 8, walls)

    def test_rounded_endpoint_does_not_create_square_corner_barrier(self):
        wall = Rect(32, 32, 2, 32)
        # Within the expanded AABB but outside the actual radius-8 rounded corner.
        result = move_circle(24.5, 26, 8, 1, 0, (wall,))
        self.assertEqual((result.x, result.y), (25.5, 26))
        hit = move_circle(16, 16, 8, 30, 30, (wall,))
        self.assertAlmostEqual(hit.x, 32 - 8 / math.sqrt(2), places=5)
        self.assertAlmostEqual(hit.y, hit.x, places=5)
        assert_clear(self, hit, 8, (wall,))

    def test_connected_segments_behave_like_one_wall(self):
        segments = tuple(Rect(32, row * 32, 2, 32) for row in range(6))
        whole = (Rect(32, 0, 2, 192),)
        for delta in ((0, 160), (4, 160), (80, 160)):
            a = move_circle(24, 16, 8, *delta, segments)
            b = move_circle(24, 16, 8, *delta, whole)
            self.assertAlmostEqual(a.x, b.x, places=5)
            self.assertAlmostEqual(a.y, b.y, places=5)

    def test_outer_boundary_and_second_contact_stop_remaining_motion(self):
        walls = fixed_map().walls
        for dx, dy in ((-500, 0), (0, -500), (-500, -500), (500, 500)):
            result = move_circle(16, 16, 8, dx, dy, walls)
            assert_clear(self, result, 8, walls)
            self.assertGreaterEqual(result.x, 10 - 1e-7)
            self.assertGreaterEqual(result.y, 10 - 1e-7)
            self.assertLessEqual(result.x, 246 + 1e-7)
            self.assertLessEqual(result.y, 182 + 1e-7)

    def test_seeded_motion_remains_clear_and_wall_order_independent(self):
        walls = fixed_map().walls
        rng = random.Random(1203)
        x, y = 16, 16
        for _ in range(1000):
            dx, dy = rng.uniform(-70, 70), rng.uniform(-70, 70)
            a = move_circle(x, y, 8, dx, dy, walls)
            b = move_circle(x, y, 8, dx, dy, walls[::-1])
            self.assertEqual(a, b)
            assert_clear(self, a, 8, walls)
            x, y = a.x, a.y


if __name__ == '__main__':
    unittest.main()
