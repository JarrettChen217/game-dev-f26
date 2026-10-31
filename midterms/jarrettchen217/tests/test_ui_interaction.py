"""Capture belongs to one source, target and visible layout generation."""
import unittest

try:
    from tank_game.ui_interaction import InteractionFrame, MenuInteraction
    from tank_game.ui_layout import Control
    from tank_game.window_state import WindowSnapshot
except ImportError:
    MenuInteraction = None


class InteractionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(MenuInteraction, 'release-inside input controller is missing')
        self.controller = MenuInteraction()
        self.controls = (Control('a', (10, 10, 100, 30), 'a', 'quit'),
                         Control('b', (120, 10, 100, 30), 'b', 'start'))
        self.frame()

    def frame(self, point=(20, 20), token=('menu',), focused=True, viewport=(920, 464), **kw):
        frame = InteractionFrame(position=point, window=WindowSnapshot(focused, viewport, True),
                                 **kw)
        return self.controller.update(frame, self.controls, context_token=token)

    def test_drag_out_back_and_release_executes_original_once(self):
        self.assertEqual(self.frame(pressed=True, held=True).pressed_control, 'a')
        self.assertIsNone(self.frame(point=(130, 20), held=True).pressed_control)
        self.assertEqual(self.frame(held=True).pressed_control, 'a')
        self.assertEqual(self.frame(released=True).activate_control, 'a')
        self.assertIsNone(self.frame(released=True).activate_control)

    def test_blank_origin_drag_and_outside_release_never_activate(self):
        self.frame(point=(0, 0), pressed=True, held=True)
        self.assertIsNone(self.frame(released=True).activate_control)
        self.frame(pressed=True, held=True)
        self.assertIsNone(self.frame(point=(130, 20), released=True).activate_control)

    def test_hold_never_repeats_and_fast_sampled_click_is_once(self):
        self.frame(pressed=True, held=True)
        for _ in range(20):
            self.assertIsNone(self.frame(held=True, pressed=True).activate_control)
        self.assertEqual(self.frame(released=True).activate_control, 'a')
        self.assertEqual(self.frame(pressed=True, released=True).activate_control, 'a')

    def test_stationary_pointer_does_not_steal_keyboard_focus_or_new_default(self):
        self.frame(navigation='down')
        self.assertIsNone(self.frame().focus_control)
        self.assertEqual(self.frame(point=(130, 20)).focus_control, 'b')
        self.frame(token=('help',))
        self.assertIsNone(self.frame(token=('help',)).focus_control)

    def test_native_focus_resize_or_context_change_cancels_before_release(self):
        for change in ({'focused': False}, {'viewport': (1000, 600)}, {'token': ('help',)}):
            with self.subTest(change=change):
                self.controller = MenuInteraction(); self.frame()
                self.frame(pressed=True, held=True)
                self.assertIsNone(self.frame(released=True, **change).activate_control)
                self.assertIsNone(self.frame(pressed=True, released=True).activate_control)
                self.frame()
                self.assertEqual(self.frame(pressed=True, released=True).activate_control, 'a')

    def test_enter_wins_new_capture_and_mouse_cannot_replace_pending_enter(self):
        result = self.frame(pressed=True, held=True, confirm_pressed=True, confirm_held=True,
                            keyboard_control='b')
        self.assertEqual(result.pressed_control, 'b')
        self.assertIsNone(self.frame(released=True, confirm_held=True).activate_control)
        self.assertEqual(self.frame(confirm_released=True).activate_control, 'b')
        self.frame(pressed=True, held=True)
        self.assertIsNone(self.frame(escape_pressed=True, released=True).activate_control)

    def test_one_idle_frame_on_a_new_page_rearms_the_next_click(self):
        self.frame(token=('help',))
        self.assertEqual(self.frame(token=('help',), pressed=True, released=True).activate_control, 'a')
