"""The renderer really scales and bolds pixels, as well as score geometry."""
import unittest

from tank_game.laika_60hz.hud import draw_match_hud
from tank_game.match_hud import MatchFacts, SessionScore
from tests.test_ui_rendering import FakeWindow


class OnePixelMask:
    """Isolate font rasterization; the real label renderer scales this pixel."""
    def __init__(self, width, height):
        pass

    def text(self, *args):
        pass

    def pget(self, x, y):
        return int(x == 0 and y == 0)


class Source60HudStyleTests(unittest.TestCase):
    def test_score_renders_double_size_bold_pixels_and_compact_settlement_spacing(self):
        window = FakeWindow()
        window.Image = OnePixelMask
        score = SessionScore(('tank-1', 'tank-2'))
        facts = MatchFacts(1, 'settling', ('tank-2',), 1.5, 3.)
        draw_match_hud(window, facts, score, origin=(204, 40))
        self.assertTrue(any(rect[1:] == (426, 3, 2, 0) for rect in window.rectangles),
                        'a font pixel must become2x2 plus the one-pixel bold extension')
        self.assertIn((204, 442, 512, 4, 5), window.rectangles)
        self.assertTrue(any(y == 448 and '1.5s' in text for _, y, text, _ in window.texts))


if __name__ == '__main__':
    unittest.main()
