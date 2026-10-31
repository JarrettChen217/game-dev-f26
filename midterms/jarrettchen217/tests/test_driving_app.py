"""Window adapter checks do not substitute for real keyboard playtesting."""

import unittest

from tank_game.app import DrivingApp
from tank_game.world import World
from tests.test_driving import open_map


class WindowStub:
    KEY_NONE = 'none'
    KEY_RETURN = 'enter'
    KEY_TAB = 'tab'
    KEY_N = 'n'
    KEY_F = 'f'
    KEY_SPACE = 'space'
    KEY_W = 'w'
    KEY_S = 's'
    KEY_A = 'a'
    KEY_D = 'd'
    KEY_UP = 'up'
    KEY_DOWN = 'down'
    KEY_LEFT = 'left'
    KEY_RIGHT = 'right'
    KEY_ESCAPE = 'esc'
    KEY_PAGEDOWN = 'pgdn'
    KEY_PAGEUP = 'pgup'

    def __init__(self):
        self.held = set()
        self.pressed = set()
        self.colors = [0] * 16
        self.exited = False
        self.time = 0.0

    def clock(self):
        """Existing frame fixtures explicitly represent one sixtieth of a second."""
        self.time += 1/60
        return self.time

    def init(self, *args, **kwargs):
        self.init_options = kwargs

    def run(self, update, draw):
        self.update_callback, self.draw_callback = update, draw

    def btn(self, key):
        return key in self.held

    def btnp(self, key, *args):
        return key in self.pressed

    def quit(self):
        self.exited = True


def confirm_result(window, app):
    """Press then release Enter through the actual result adapter."""
    window.pressed = {'enter'}
    app.update()
    window.pressed.clear()
    window.held.discard('enter')
    app.update()


class DrivingAppTests(unittest.TestCase):
    def test_window_keys_enter_shared_boundary_and_release_stops(self):
        for forward, turn in (('w', 'd'), ('up', 'right')):
            window = WindowStub()
            world = World(open_map())
            app = DrivingApp(window, world, clock=window.clock)
            self.assertEqual(window.init_options['fps'], 60)
            window.held = {forward, turn}
            app.update()
            self.assertEqual(app.scene['tanks'][0]['heading_deg'], 3)
            self.assertEqual(app.scene['tanks'][0]['x'], 100.75)
            before = world._tanks['tank-1']
            window.held.clear()
            app.update()
            self.assertEqual(before, world._tanks['tank-1'])
            self.assertEqual(world.rejected_actions, 0)

    def test_all_reverse_left_aliases_are_wired(self):
        for reverse, turn in (('s', 'a'), ('down', 'left')):
            window = WindowStub()
            app = DrivingApp(window, World(open_map()), clock=window.clock)
            window.held = {reverse, turn}
            app.update()
            self.assertEqual(app.scene['tanks'][0]['heading_deg'], 357)
            self.assertLess(app.world._tanks['tank-1'].x, 100)

    def test_inspection_scroll_does_not_pause_and_escape_opens_pause_without_step(self):
        window = WindowStub()
        app = DrivingApp(window, clock=window.clock)
        app.ui.inspection_visible = True
        window.pressed = {'pgdn'}
        app.update()
        self.assertGreater(app.scroll, 0)
        self.assertEqual(app.scene['observation_tick'], 1)
        window.pressed = {'pgup'}
        app.update()
        self.assertEqual(app.scroll, 0)
        self.assertEqual(app.scene['observation_tick'], 2)
        window.pressed = {'esc'}
        app.update()
        self.assertFalse(window.exited)
        self.assertEqual(app.ui.screen, 'pause')
        self.assertEqual(app.world.observe('tank-1')['observation_tick'], 2)
