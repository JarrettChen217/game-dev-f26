"""Presentation routing contracts independent of engine/simulation."""
import unittest

from tank_game.ui import MenuSelection, UIState, result_actions


class UIModelTests(unittest.TestCase):
    def test_fixed_random_display_order_matches_left_right_selection(self):
        ui = UIState()
        ui.focus = 'map'
        ui.handle('left', 0)
        self.assertFalse(ui.selection.random_map)
        ui.handle('right', .2)
        self.assertTrue(ui.selection.random_map)
        ui.handle('confirm', .3)
        self.assertTrue(ui.selection.random_map)
        self.assertGreater(ui.feedback_until, .3)

    def test_checkbox_preserves_duel_preferences_and_skips_inactive_rows(self):
        ui = UIState()
        ui.selection.strategy = 'hard'
        ui.focus = 'bot'
        ui.handle('confirm', 0)
        self.assertEqual(ui.selection.effective(), (False, 'hard', False))
        self.assertNotIn('strength', ui.rows())
        ui.handle('down', .01)
        self.assertEqual(ui.focus, 'start')
        ui.focus = 'bot'
        ui.handle('right', .02)
        self.assertEqual(ui.selection.effective(), (True, 'hard', True))

    def test_help_back_is_one_action_and_focus_clamps(self):
        ui = UIState()
        ui.focus = 'help'
        self.assertIsNone(ui.handle('confirm', 0))
        self.assertEqual(ui.screen, 'help')
        self.assertIsNone(ui.handle('back', .01))
        self.assertEqual(ui.screen, 'menu')
        self.assertEqual(ui.focus, 'help')
        ui.focus = 'bot'
        ui.handle('up', .02)
        self.assertEqual(ui.focus, 'tutorial')
        ui.focus = 'quit'
        ui.handle('down', .03)
        self.assertEqual(ui.focus, 'quit')

    def test_start_confirmation_waits_then_can_cancel(self):
        ui = UIState()
        self.assertIsNone(ui.handle('confirm', 1))
        self.assertEqual(ui.screen, 'starting')
        self.assertIsNone(ui.handle('tick', 1.1))
        self.assertIsNone(ui.handle('back', 1.11))
        self.assertEqual(ui.screen, 'menu')
        ui.handle('confirm', 2)
        self.assertEqual(ui.handle('tick', 2.13), 'start')

    def test_results_have_only_valid_commands(self):
        self.assertEqual(result_actions(False), ('retry', 'menu', 'quit'))
        self.assertEqual(result_actions(True), ('retry', 'next_map', 'menu', 'quit'))
        ui = UIState()
        ui.screen, ui.focus = 'results', 'retry'
        ui.handle('down', 0)
        self.assertEqual(ui.focus, 'next_map')
        self.assertIsNone(ui.handle('confirm', .005))
        self.assertEqual(ui.pending_result, 'next_map')
        self.assertEqual(ui.handle('release', .01), 'next_map')
        self.assertIsNone(ui.handle('back', .02))
        self.assertEqual(ui.focus, 'quit')
        self.assertTrue(ui.quit_armed)

    def test_invalid_choices_fail_before_world_creation(self):
        with self.assertRaises(ValueError):
            MenuSelection(strategy='extreme').effective()
