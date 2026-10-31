"""The60Hz window advances real world steps and draws current state only."""
import platform
import sys
import unittest

from tank_game.app import DrivingApp
from tests.test_original_laika_app import OriginalWindow
from tests.test_realtime import Clock


@unittest.skipUnless(sys.platform == 'darwin' and platform.machine() == 'arm64',
                     'optional source60Hz artifact currently targets macOS arm64')
class Source60AppTests(unittest.TestCase):
    def app(self):
        from tank_game.laika_60hz.session import Source60RoundSession
        session = Source60RoundSession(1000)
        self.addCleanup(session.close)
        window, clock = OriginalWindow(), Clock()
        app = DrivingApp(window, strategy='laika', random_session=session, clock=clock)
        self.addCleanup(app.close)
        return window, clock, app

    def test_display_and_real_world_advance_sixty_steps_without_external_bot(self):
        window, clock, app = self.app()
        self.assertIsNone(app.scheduler)
        self.assertEqual(list(app.runner.controllers), ['tank-1'])
        self.assertIn('60Hz SOURCE', window.init_options['title'])
        for _ in range(60):
            clock.now += 1/60
            app.update()
            app.draw()  # World60.render_scene raises if interpolation is attempted.
        self.assertEqual(app.world.diagnostics['world_steps'], 60)
        self.assertEqual(app.world.diagnostics['laika_calls'], 60)
        self.assertTrue(window.triangles)
        self.assertTrue(any('60Hz' in text for _, _, text, _ in window.texts))
        self.assertFalse(any('25Hz' in text for _, _, text, _ in window.texts))

    def test_slow_display_catches_up_without_discarding_world_time(self):
        _, clock, app = self.app()
        clock.now += .5
        app.update()
        self.assertEqual(app.world.diagnostics['world_steps'], 30)
        self.assertAlmostEqual(app.scene['duel']['elapsed'], .5)

    def test_pause_does_not_advance_and_resume_does_not_catch_up_paused_time(self):
        window, clock, app = self.app()
        window.pressed, window.held = {'esc'}, {'esc'}
        clock.now += 1/60
        app.update()
        self.assertEqual(app.ui.screen, 'pause')
        before = app.world.diagnostics['world_steps']
        window.pressed.clear()
        for _ in range(10):
            clock.now += 1
            app.update()
        self.assertEqual(app.world.diagnostics['world_steps'], before)


if __name__ == '__main__':
    unittest.main()
