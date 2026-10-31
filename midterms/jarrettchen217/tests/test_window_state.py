"""Native viewport validity must reject bars even when logical coordinates round in."""
import unittest

try:
    from tank_game.window_state import NativeWindowObserver, RawWindow
except ImportError:
    NativeWindowObserver = None


class WindowStateTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(NativeWindowObserver, 'native window observer is missing')

    def test_focus_and_epoch_are_not_inferred_from_logical_size(self):
        state = [RawWindow(True, (1200, 700), (500, 350), (1, 0))]
        observer = NativeWindowObserver(reader=lambda: state[0])
        first = observer.sample(None)
        state[0] = RawWindow(True, (1200, 700), (500, 350), (1, 1))
        self.assertNotEqual(first.viewport_token, observer.sample(None).viewport_token)
        state[0] = RawWindow(False, (1200, 700), (500, 350), (1, 2))
        self.assertFalse(observer.sample(None).focused)

    def test_letterbox_outside_and_half_open_canvas_edge(self):
        state = [RawWindow(True, (920, 600), (100, 67), (1,))]
        observer = NativeWindowObserver(reader=lambda: state[0])
        self.assertFalse(observer.sample(None).inside_canvas)
        state[0] = RawWindow(True, (920, 600), (100, 68), (1,))
        self.assertTrue(observer.sample(None).inside_canvas)
        state[0] = RawWindow(True, (920, 600), (920, 100), (1,))
        self.assertFalse(observer.sample(None).inside_canvas)
