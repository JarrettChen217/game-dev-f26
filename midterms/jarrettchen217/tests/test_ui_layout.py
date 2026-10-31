"""Visible control geometry is the sole hit-test boundary."""
import unittest

from tank_game.ui import UIState

try:
    from tank_game.ui_layout import layout_controls
except ImportError:
    layout_controls = None


class ControlLayoutTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(layout_controls, 'shared control geometry is missing')
        self.ui = UIState()

    def test_choice_labels_are_focus_only_and_concrete_values_do_not_overlap(self):
        controls = layout_controls(self.ui)
        self.assertEqual(next(c for c in controls if c.id == 'strength:label').operation, None)
        simple = next(c for c in controls if c.id == 'strength:simple')
        hard = next(c for c in controls if c.id == 'strength:hard')
        self.assertEqual((simple.value, hard.value), ('simple', 'hard'))
        self.assertTrue(simple.contains((simple.rect[0], simple.rect[1])))
        self.assertFalse(simple.contains((simple.rect[0]+simple.rect[2], simple.rect[1])))
        self.assertLessEqual(simple.rect[0]+simple.rect[2], hard.rect[0])
        self.ui.selection.bot_enabled = False
        self.assertFalse(any(c.focus in ('strength', 'map') for c in layout_controls(self.ui)))

    def test_results_follow_board_origin_and_random_visibility(self):
        self.ui.screen = 'results'
        a = layout_controls(self.ui, origin=(204, 40))
        b = layout_controls(self.ui, origin=(16, 40))
        self.assertEqual(a[0].rect[0]-b[0].rect[0], 188)
        self.assertIn('next_map', [c.id for c in a])
        self.ui.selection.random_map = False
        self.assertNotIn('next_map', [c.id for c in layout_controls(self.ui)])

    def test_tutorial_layers_and_all_control_bounds_fit_canvas(self):
        for phase in ('active', 'success', 'error', 'complete'):
            for paused in (False, True):
                controls = layout_controls(self.ui, tutorial_phase=phase, tutorial_paused=paused)
                if phase == 'complete':
                    self.assertEqual([c.id for c in controls], ['return_menu'])
                if paused or phase == 'error':
                    self.assertFalse(any(c.id == 'skip_tutorial' and c.rect[1] < 40 for c in controls))
                for c in controls:
                    x, y, w, h = c.rect
                    self.assertTrue(0 <= x < x+w <= 920, c)
                    self.assertTrue(0 <= y < y+h <= 464, c)
