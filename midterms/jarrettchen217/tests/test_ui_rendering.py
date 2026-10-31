"""Public UI placement and visibility do not change simulation."""
import unittest

from tank_game.app import DrivingApp
from tank_game.ui_rendering import board_origin, draw_hud, draw_menu
from tank_game.world import World
from tests.test_driving_app import WindowStub
from tests.test_realtime import Clock


class FakeWindow(WindowStub):
    def __init__(self):
        super().__init__()
        self.texts = []
        self.rectangles = []

    def text(self, x, y, s, color):
        self.texts.append((x, y, s, color))

    def rect(self, *args):
        self.rectangles.append(args)

    def rectb(self, *args):
        self.rectangles.append(args)

    def cls(self, *args):
        pass

    def pget(self, *args):
        return 7

    def pset(self, *args):
        pass

    def tri(self, *args):
        pass

    def circ(self, *args):
        pass

    def circb(self, *args):
        pass


class LayoutTests(unittest.TestCase):
    def test_menu_shows_both_choices_indented_and_marks_active_value(self):
        window = FakeWindow()
        app = DrivingApp(window, menu=True, clock=window.clock)
        self.addCleanup(app.close)
        app.ui.focus = 'strength'
        app.ui.handle('right', 1)
        draw_menu(window, app.ui, app.keymap, 1.01)
        for value in ('Simple', 'Hard', 'Fixed', 'Random'):
            self.assertTrue(any(t[2] == value for t in window.texts), value)
        bot_x = next(t[0] for t in window.texts if 'Enable bot' in t[2])
        strength_x = next(t[0] for t in window.texts if t[2] == 'Bot strength: ')
        self.assertGreater(strength_x, bot_x)
        self.assertEqual(sum(t[2] == 'Hard' for t in window.texts), 2)
        self.assertEqual(sum(t[2] == 'Simple' for t in window.texts), 1)
        self.assertTrue(all(t[3] == 3 for t in window.texts if t[2] == 'Hard'))
        window.texts.clear()
        draw_menu(window, app.ui, app.keymap, 2)
        self.assertTrue(all(t[3] == 0 for t in window.texts if t[2] == 'Hard'))
        self.assertTrue(any(rect[3] == 1 for rect in window.rectangles))

    def test_navigation_hints_match_starting_and_results_escape(self):
        window = FakeWindow()
        app = DrivingApp(window, menu=True, clock=window.clock)
        self.addCleanup(app.close)
        app.ui.screen = 'starting'
        draw_menu(window, app.ui, app.keymap, 0)
        self.assertIn('Esc: cancel', ' '.join(t[2] for t in window.texts))
        window.texts.clear()
        scene = World().observe('tank-1')
        scene['round_status'] = 'GAME_OVER'
        draw_hud(window, scene, strategy='simple', seed=None, keymap=app.keymap,
                 origin=(204,40))
        hint = ' '.join(t[2] for t in window.texts)
        self.assertIn('Esc: select Quit', hint)
        self.assertNotIn('ESCAPE: quit', hint)

    def test_board_is_fully_visible_in_both_layouts(self):
        self.assertEqual(board_origin(False), (204, 40))
        self.assertEqual(board_origin(True), (16, 40))
        for mode in (False, True):
            x, y = board_origin(mode)
            self.assertLessEqual(x+512, 920)
            self.assertLessEqual(y+384, 464)

    def test_hidden_paging_is_inactive_and_toggle_keeps_simulation_equal(self):
        clock = Clock()
        a, b = FakeWindow(), FakeWindow()
        first = DrivingApp(a, World(), clock=clock)
        second = DrivingApp(b, World(), clock=clock)
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        a.pressed = {'pgdn'}
        clock.now = 1/60
        first.update()
        second.update()
        self.assertEqual(first.scroll, 0)
        self.assertFalse(first.ui.inspection_visible)
        a.pressed = {'tab'}
        clock.now += 1/60
        first.update()
        second.update()
        self.assertTrue(first.ui.inspection_visible)
        self.assertEqual(first.scene, second.scene)
        first.draw()
        second.draw()
        self.assertTrue(any('PUBLIC' in t[2] for t in a.texts))
        self.assertFalse(any('PUBLIC' in t[2] for t in b.texts))

    def test_hud_uses_capacity_and_public_readiness_and_fits_board(self):
        scene = World().observe('tank-1')
        scene['rules']['max_bullets'] = 12
        scene['self_status']['active_bullets'] = 3
        window = FakeWindow()
        app = DrivingApp(window, World(), clock=window.clock)
        draw_hud(window, scene, strategy='simple', seed=None,
                 keymap=app.keymap, origin=(204,40))
        texts = ' '.join(t[2] for t in window.texts)
        self.assertIn('9/12', texts)
        self.assertNotIn('BOT', texts)
        for x,y,value,_ in window.texts:
            self.assertGreaterEqual(x, 204)
            self.assertLessEqual(x+len(value)*4, 716)
            self.assertTrue(y < 40 or y >= 424)
