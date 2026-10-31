"""Menu transitions exercise the actual adapter with a controlled clock."""
import json
import tempfile
import unittest
from pathlib import Path

from tank_game.agents import AgentScheduler, InlineWorker
from tank_game.app import DrivingApp
from tank_game.keymap import DEFAULT_KEYMAP_PATH
from tank_game.strategies import make_policy
from tests.test_driving_app import WindowStub
from tests.test_realtime import Clock


class MenuAppTests(unittest.TestCase):
    def make_app(self, **kwargs):
        window, clock = WindowStub(), Clock()
        app = DrivingApp(window, menu=True, clock=clock,
                         scheduler_factory=lambda: AgentScheduler(InlineWorker(make_policy('simple'))),
                         **kwargs)
        self.addCleanup(app.close)
        app.ui.focus = 'start'  # These tests intentionally exercise normal Start.
        return window, clock, app

    def test_idle_menu_has_no_world_or_worker_and_start_can_cancel(self):
        window, clock, app = self.make_app()
        self.assertIsNone(app.world)
        clock.now = 60
        app.update()
        self.assertIsNone(app.scheduler)
        window.pressed = {'enter'}
        app.update()
        self.assertEqual(app.ui.screen, 'starting')
        window.pressed = {'esc'}
        clock.now += .05
        app.update()
        self.assertIsNone(app.world)
        self.assertEqual(app.ui.screen, 'menu')
        self.assertFalse(window.exited)

    def test_start_resets_menu_time_and_waits_for_confirm_and_fire_release(self):
        window, clock, app = self.make_app()
        app.ui.selection.bot_enabled = False
        clock.now = 100
        window.pressed = {'enter'}
        window.held = {'enter', 'space', 'w'}
        app.update()
        window.pressed.clear()
        clock.now += .13
        app.update()
        self.assertEqual(app.scene['observation_tick'], 0)
        before = app.scene['tanks'][0]
        clock.now += 1/60
        app.update()
        self.assertEqual(app.scene['tanks'][0], before)
        self.assertEqual(app.scene['bullets'], [])
        window.held.clear()
        clock.now += 1/60
        app.update()
        window.held = {'w'}
        clock.now += 1/60
        app.update()
        self.assertNotEqual(app.scene['tanks'][0], before)

    def test_help_escape_never_also_quits(self):
        window, _clock, app = self.make_app()
        app.ui.focus = 'help'
        window.pressed = {'enter'}
        app.update()
        self.assertEqual(app.ui.screen, 'help')
        window.pressed = {'esc'}
        app.update()
        self.assertEqual(app.ui.screen, 'menu')
        self.assertFalse(window.exited)

    def test_random_only_conflict_preserves_menu_choices(self):
        data = json.loads(DEFAULT_KEYMAP_PATH.read_text())
        data['bindings']['quit'] = ['N']
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'keys.json'
            path.write_text(json.dumps(data))
            window, clock, app = self.make_app(keymap_path=path)
            window.pressed = {'enter'}
            app.update()
            window.pressed.clear()
            clock.now = .13
            app.update()
            self.assertEqual(app.ui.screen, 'menu')
            self.assertIsNone(app.world)
            self.assertIn('next_map', app.ui.error)
            app.ui.selection.random_map = False
            window.pressed = {'enter'}
            app.update()
            clock.now += .13
            window.pressed.clear()
            app.update()
            self.assertIn('duel', app.scene)
