"""The optional accelerator must retain every original sample and palette pixel."""
import importlib.util
import random
import unittest

from tank_game.rendering import SmoothTankRenderer, tank_coverage


@unittest.skipUnless(importlib.util.find_spec('numpy'), 'optional existing NumPy runtime')
class ArrayRenderingTests(unittest.TestCase):
    def test_array_coverage_matches_reference_at_fractional_and_boundary_poses(self):
        from tank_game.rendering_numpy import array_tank_coverage
        rng = random.Random(16)
        poses = [(24, heading, x, y) for heading in (0, 45, 90, 180, 270, 359.99)
                 for x, y in ((0, 0), (.5, .5), (.125, .875))]
        poses += [(rng.choice((12, 24)), rng.uniform(0, 360), rng.random(), rng.random())
                  for _ in range(12)]
        for pose in poses:
            with self.subTest(pose=pose):
                self.assertEqual(array_tank_coverage(*pose), tank_coverage(*pose))

    def test_rendered_pixels_match_over_different_backgrounds(self):
        from tank_game.rendering_numpy import array_tank_coverage
        class Pixels:
            def __init__(self):
                self.values = {}
            def pget(self, x, y):
                return self.values.get((x, y), (6, 13, 5)[(x+y) % 3])
            def pset(self, x, y, color):
                self.values[x, y] = color
        reference, accelerated = Pixels(), Pixels()
        pose = (100.123, 110.456, 12, 16.789)
        SmoothTankRenderer().draw(reference, pose, origin=(16, 40), scale=2)
        SmoothTankRenderer(coverage=array_tank_coverage).draw(
            accelerated, pose, origin=(16, 40), scale=2)
        self.assertEqual(reference.values, accelerated.values)
