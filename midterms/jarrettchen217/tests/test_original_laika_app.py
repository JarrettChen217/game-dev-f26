"""Native input/display host around the original simulation, without a second bot."""
import shutil
import subprocess
import sys
import unittest

from tank_game.app import DrivingApp
from tests.test_realtime import Clock
from tests.test_ui_rendering import FakeWindow


class OriginalWindow(FakeWindow):
    def __init__(self):
        super().__init__()
        self.triangles = []

    def tri(self, *args):
        self.triangles.append(args)


@unittest.skipUnless(shutil.which('node'), 'optional original profile requires existing Node')
class OriginalAppTests(unittest.TestCase):
    def app(self):
        from tank_game.original_laika.session import OriginalRoundSession
        session = OriginalRoundSession(1000)
        self.addCleanup(session.close)
        window, clock = OriginalWindow(), Clock()
        app = DrivingApp(window, strategy='laika', random_session=session, clock=clock)
        self.addCleanup(app.close)
        return window, clock, app

    def test_original_bot_is_internal_while_local_window_keeps_60hz(self):
        window, clock, app = self.app()
        self.assertIsNone(app.scheduler)
        self.assertEqual(list(app.runner.controllers), ['tank-1'])
        self.assertEqual(window.init_options['fps'], 60)
        self.assertIn('ORIGINAL', window.init_options['title'])
        for _ in range(3):
            clock.now += 1/60
            app.update()
        self.assertEqual(app.world.observe('tank-1')['observation_tick'], 1)
        window.pressed, window.held = {'esc'}, {'esc'}
        clock.now += 1/60
        app.update()
        self.assertEqual(app.ui.screen, 'pause')
        self.assertNotIn('menu', app.ui.rows(), 'original session must not silently restart with native rules')
        before = app.world.raw_render
        window.pressed.clear()
        for _ in range(10):
            clock.now += 1
            app.update()
        self.assertEqual(app.world.raw_render, before)
        app.close()
        self.assertIsNotNone(app.world.process.poll())

    def test_retry_next_map_and_rendered_profile_are_explicit(self):
        window, _, app = self.app()
        original = app.world.raw_render
        self.assertTrue(app.random_session.transition('retry', allow_active=True))
        self.assertEqual(app.world.raw_render, original)
        self.assertTrue(app.random_session.transition('next_map', allow_active=True))
        self.assertEqual(app.random_session.record.seed, 1001)
        self.assertNotEqual(app.world.raw_render, original)
        app.scene = app.world.observe('tank-1')
        before = app.world.raw_render
        app.draw()
        self.assertEqual(app.world.raw_render, before)
        self.assertTrue(any('Original' in text for _,_,text,_ in window.texts))
        self.assertTrue(window.triangles)
        for triangle in window.triangles:
            self.assertTrue(all(0 <= value <= 920 for value in triangle[:6:2]))
            self.assertTrue(all(0 <= value <= 464 for value in triangle[1:6:2]))

    def test_cli_inspection_selects_original_and_rejects_mixed_profiles(self):
        command = [sys.executable, '-m', 'tank_game', '--duel', '--strategy', 'laika',
                   '--rules-profile', 'laika-original']
        result = subprocess.run(command+['--map-seed','1000','--inspect'],
                                text=True,capture_output=True,timeout=10,check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"rules_profile": "laika-original-v1"', result.stdout)
        self.assertIn('"tick_rate": 25', result.stdout)
        result = subprocess.run(command+['--collision-profile','rectangle','--inspect'],
                                text=True,capture_output=True,timeout=10,check=False)
        self.assertNotEqual(result.returncode, 0)
