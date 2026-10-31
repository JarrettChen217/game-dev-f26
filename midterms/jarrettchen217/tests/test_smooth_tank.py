"""Tank raster coverage preserves fractional poses and transparent backgrounds."""

import unittest

from tank_game.rendering import PALETTE, SmoothTankRenderer, tank_coverage


class PixelSurface:
    def __init__(self, background):
        self.background = background
        self.pixels = {}

    def pget(self, x, y):
        return self.pixels.get((x, y), self.background)

    def pset(self, x, y, color):
        self.pixels[x, y] = color


class SmoothTankTests(unittest.TestCase):
    def test_coverage_has_partial_edges_and_never_leaves_body_envelope(self):
        for heading in (0, 30, 45, 90, 135, 359.75):
            pixels = tank_coverage(16, heading, .25, .75)
            self.assertTrue(any(0 < sum(counts) < 16 for _, _, counts in pixels))
            for x, y, counts in pixels:
                self.assertTrue(0 < sum(counts) <= 16)
                self.assertLessEqual((x - .25) ** 2 + (y - .75) ** 2, 18 ** 2)

    def test_fractional_translation_and_rotation_change_coverage(self):
        original = tank_coverage(16, 45, 0, 0)
        self.assertNotEqual(original, tank_coverage(16, 45, .25, 0))
        self.assertNotEqual(original, tank_coverage(16, 45.25, 0, 0))
        self.assertEqual(original, tank_coverage(16, 45, 0, 0))

    def test_palette_keeps_base_colors_and_fits_pyxel_budget(self):
        self.assertLessEqual(len(PALETTE), 256)
        self.assertEqual((PALETTE[0], PALETTE[5], PALETTE[11]),
                         (0x182126, 0x606563, 0x52B788))

    def test_edge_blending_uses_actual_floor_and_preserves_interior_and_background(self):
        surfaces = [PixelSurface(6), PixelSurface(13)]
        renderer = SmoothTankRenderer()
        for surface in surfaces:
            renderer.draw(surface, (40.125, 50.375, 8, 45), origin=(16, 40), scale=2)
            self.assertNotIn((0, 0), surface.pixels)
            self.assertTrue(any(index >= 16 for index in surface.pixels.values()))
            self.assertTrue(all(0 <= index < len(PALETTE) for index in surface.pixels.values()))
            self.assertIn(11, surface.pixels.values())
        self.assertEqual(set(surfaces[0].pixels), set(surfaces[1].pixels))
        self.assertNotEqual(surfaces[0].pixels, surfaces[1].pixels)


if __name__ == '__main__':
    unittest.main()
