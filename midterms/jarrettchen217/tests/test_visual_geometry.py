"""Visual tank silhouette stays inside the shared circular body boundary."""

import math
import unittest
from dataclasses import replace

from tank_game.map import Spawn, fixed_map
from tank_game.rendering import tank_polygons
from tank_game.world import World


class TankVisualTests(unittest.TestCase):
    def test_body_tracks_and_barrel_fit_circle_at_every_heading(self):
        for heading in range(0, 360, 15):
            radius = World().observe('tank-1')['tanks'][0]['radius']
            polygons = tank_polygons(40, 50, radius, heading)
            self.assertEqual(set(polygons), {'left_track', 'right_track', 'body', 'barrel'})
            for points in polygons.values():
                for x, y in points:
                    self.assertLessEqual(math.hypot(x - 40, y - 50), radius)

    def test_barrel_indicates_heading_without_changing_world_center(self):
        right = tank_polygons(40, 50, 5, 0)['barrel']
        down = tank_polygons(40, 50, 5, 90)['barrel']
        self.assertGreater(max(x for x, y in right), 44)
        self.assertGreater(max(y for x, y in down), 54)
        for (rx, ry), (dx, dy) in zip(right, down, strict=True):
            self.assertAlmostEqual(dx - 40, -(ry - 50))
            self.assertAlmostEqual(dy - 50, rx - 40)


class EnlargedTankTests(unittest.TestCase):
    def test_larger_public_body_matches_rules_and_fits_every_floor_cell(self):
        scene = World().observe('tank-1')
        radius = scene['tanks'][0]['radius']
        self.assertEqual(radius, 8)
        self.assertEqual(radius, scene['rules']['tank_radius'])
        maze = fixed_map()
        for row in range(maze.rows):
            for column in range(maze.columns):
                spawn = Spawn((column + .5) * maze.tile_size,
                              (row + .5) * maze.tile_size, 0)
                self.assertTrue(replace(maze, spawn=spawn).is_legal_spawn(radius))
        self.assertGreater(maze.tile_size - maze.wall_thickness, 2 * radius)
