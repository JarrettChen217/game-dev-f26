"""Regression for Hao's report: walls must be thin grid edges, not solid cells."""

import unittest

from tank_game.map import fixed_map


class EdgeWallRegressionTests(unittest.TestCase):
    def test_fixed_map_has_thin_walls_instead_of_solid_tiles(self):
        for wall in fixed_map().walls:
            self.assertLessEqual(min(wall.width, wall.height), 2)
