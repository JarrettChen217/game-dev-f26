"""Actual application routing: fresh input, frozen pause and isolated sessions."""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from tank_game.app import DrivingApp
from tank_game.tutorial import make_tutorial_scenario
from tests.test_realtime import Clock
from tests.test_tutorial_scenarios import goal_around_current
from tests.test_ui_rendering import FakeWindow


class TutorialWindow(FakeWindow):
    MOUSE_BUTTON_LEFT = 'mouse-left'
    mouse_x = 0
    mouse_y = 0
    cursor_visible = False

    def mouse(self, visible):
        self.cursor_visible = visible


class TutorialAppTests(unittest.TestCase):
    def make_app(self, **kwargs):
        window, clock = TutorialWindow(), Clock()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        kwargs.setdefault('tutorial_progress_path', Path(directory.name) / 'progress.json')
        app = DrivingApp(window, menu=True, clock=clock, **kwargs)
        self.addCleanup(app.close)
        return window, clock, app

    def frame(self, window, clock, app, pressed=(), held=(), dt=1/60):
        window.pressed, window.held = set(pressed), set(held)
        clock.now += dt
        app.update()

    def enter_tutorial(self, **kwargs):
        w, clock, app = self.make_app(**kwargs)
        self.assertTrue(app._start_tutorial())
        self.frame(w, clock, app)
        return w, clock, app

    def select_step(self, w, clock, app, step):
        app.tutorial.scenario.world.close()
        app.tutorial.scenario = make_tutorial_scenario(step)
        app.tutorial.retry()
        app.world = app.tutorial.scenario.world
        app.scene = app.world.observe('tank-1')
        app._reset_tutorial_input()
        self.frame(w, clock, app)

    def test_new_enter_required_between_steps(self):
        w, clock, app = self.enter_tutorial()
        goal_around_current(app.tutorial)
        for _ in range(15):
            self.frame(w, clock, app, ('enter',), ('enter',))
        self.assertEqual(app.tutorial.phase, 'success')
        self.frame(w, clock, app, ('enter',), ('enter',), dt=10)
        self.assertEqual(app.tutorial.step_number, 1)
        self.frame(w, clock, app)
        self.frame(w, clock, app, ('enter',), ('enter',))
        self.assertEqual(app.tutorial.step_number, 1)
        self.frame(w, clock, app)
        self.assertEqual(app.tutorial.step_number, 2)

    def test_success_navigation_can_skip_without_advancing_or_saving(self):
        w, clock, app = self.enter_tutorial()
        app.tutorial.phase = 'success'
        self.frame(w, clock, app)
        self.assertEqual(app.tutorial_focus, 'advance')
        self.frame(w, clock, app, ('down',))
        self.assertEqual(app.tutorial_focus, 'skip_tutorial')
        self.frame(w, clock, app, ('enter',), ('enter',))
        self.assertEqual(app.tutorial.step_number, 1)
        self.frame(w, clock, app)
        self.assertEqual((app.ui.screen, app.ui.focus), ('menu', 'start'))
        self.assertFalse(app.tutorial_progress_path.exists())
        app._start_tutorial()
        self.assertEqual(app.tutorial.step_number, 1)

    def test_real_success_assigns_continue_before_the_first_success_draw(self):
        w, clock, app = self.enter_tutorial()
        goal_around_current(app.tutorial)
        while app.tutorial.phase == 'active':
            self.frame(w, clock, app)
        self.assertEqual(app.tutorial_focus, 'advance')

    def test_complete_escape_returns_to_menu_instead_of_pause(self):
        w, clock, app = self.enter_tutorial()
        app.tutorial.phase = 'complete'
        self.frame(w, clock, app, ('esc',), ('esc',))
        self.assertNotEqual(app.ui.screen, 'tutorial_pause')
        self.frame(w, clock, app)
        self.assertEqual((app.ui.screen, app.ui.focus), ('menu', 'start'))

    def test_success_and_error_resume_preserve_phase_retry_resets_current_step(self):
        for phase in ('success', 'error'):
            with self.subTest(phase=phase):
                w, clock, app = self.enter_tutorial()
                self.select_step(w, clock, app, 3)
                app.tutorial.phase = phase
                self.frame(w, clock, app)
                self.frame(w, clock, app, ('esc',), ('esc',))
                self.frame(w, clock, app)
                app._tutorial_operation('resume')
                self.frame(w, clock, app)
                self.assertEqual(app.tutorial.phase, phase)
                self.assertEqual(app.tutorial_focus, 'advance' if phase == 'success'
                                 else 'retry_step')
                app._tutorial_operation('retry_step')
                self.assertEqual(app.tutorial.step_number, 3)
                self.assertEqual(app.tutorial.phase, 'active')

    def test_active_enter_never_activates_skip_focus(self):
        w, clock, app = self.enter_tutorial()
        app.tutorial_focus = 'skip_tutorial'
        self.frame(w, clock, app, ('enter',), ('enter',))
        self.frame(w, clock, app)
        self.assertEqual(app.ui.screen, 'tutorial')
        self.assertEqual(app.tutorial.step_number, 1)

    def test_held_fire_and_mouse_do_not_leak_after_skip_retry_or_advance(self):
        w, clock, app = self.enter_tutorial()
        self.select_step(w, clock, app, 3)
        self.frame(w, clock, app, ('space',), ('space',))
        self.assertTrue(app.tutorial.shot_fired)
        self.frame(w, clock, app, ('esc',), ('esc',))
        self.frame(w, clock, app)
        app.tutorial_focus = 'retry_step'
        self.frame(w, clock, app, ('enter',), ('enter', 'space', 'mouse-left'))
        self.frame(w, clock, app, held=('space', 'mouse-left'))
        self.assertEqual(app.ui.screen, 'tutorial')
        self.frame(w, clock, app, ('space',), ('space', 'mouse-left'))
        self.assertFalse(app.tutorial.shot_fired)
        self.frame(w, clock, app)
        self.frame(w, clock, app, ('space',), ('space',))
        self.assertTrue(app.tutorial.shot_fired)
        app._skip_tutorial()
        self.frame(w, clock, app, ('enter',), ('enter', 'space', 'mouse-left'))
        self.assertEqual(app.ui.screen, 'menu')
        self.assertIsNone(app.world)
        self.frame(w, clock, app)
        self.assertIsNone(app.world)

    def test_pause_freezes_dwell_bullets_effects_and_resume_has_no_catchup(self):
        for step, ticks in ((1, 0), (4, 20), (4, 92)):
            with self.subTest(step=step, ticks=ticks):
                w, clock, app = self.enter_tutorial()
                self.select_step(w, clock, app, step)
                if step == 1:
                    goal_around_current(app.tutorial)
                    for _ in range(8):
                        self.frame(w, clock, app)
                else:
                    self.frame(w, clock, app, ('space',))
                    for _ in range(ticks):
                        self.frame(w, clock, app)
                before, dwell = app.scene, app.tutorial.goal_dwell_seconds
                self.frame(w, clock, app, ('esc',), ('esc',))
                self.frame(w, clock, app, dt=60)
                self.assertEqual(app.ui.screen, 'tutorial_pause')
                self.assertEqual(app.scene, before)
                self.assertEqual(app.tutorial.goal_dwell_seconds, dwell)
                self.frame(w, clock, app, ('esc',), ('esc',))
                self.frame(w, clock, app, dt=60)
                self.assertEqual(app.ui.screen, 'tutorial')
                self.assertEqual(app.scene, before)
                self.frame(w, clock, app, dt=60)
                self.assertEqual(app.scene, before)  # release barrier discards elapsed time
                self.frame(w, clock, app)
                self.assertLessEqual(app.scene['observation_tick']-before['observation_tick'], 1)

    def test_skip_restores_menu_selection_and_start_focus(self):
        w, clock, app = self.make_app()
        app.ui.selection.strategy, app.ui.selection.random_map = 'hard', False
        before = replace(app.ui.selection)
        app._start_tutorial()
        self.frame(w, clock, app)
        self.frame(w, clock, app, ('esc',), ('esc',))
        self.frame(w, clock, app)
        app.tutorial_focus = 'skip_tutorial'
        self.frame(w, clock, app, ('enter',), ('enter',))
        self.frame(w, clock, app)
        self.assertEqual((app.ui.screen, app.ui.focus), ('menu', 'start'))
        self.assertEqual(app.ui.selection, before)
        self.assertIsNone(app.tutorial)
        self.assertIsNone(app.world)

    def test_tutorial_creates_no_policy_worker(self):
        with patch('tank_game.process_worker.ProcessWorker', side_effect=AssertionError('unexpected worker')):
            w, clock, app = self.enter_tutorial()
            self.select_step(w, clock, app, 3)
            self.assertIsNone(app.scheduler)
            self.assertIsNone(app.session)
            self.frame(w, clock, app, ('space',))
            for _ in range(300):
                self.frame(w, clock, app)
            self.assertEqual(app.tutorial.phase, 'success')

    def test_failed_scenario_creation_preserves_recoverable_state(self):
        w, clock, app = self.make_app()
        with patch('tank_game.app.TutorialSession', side_effect=ValueError('fixture map')):
            self.assertFalse(app._start_tutorial())
        self.assertEqual(app.ui.screen, 'menu')
        self.assertIn('fixture map', app.ui.error)
        self.assertTrue(app._start_tutorial())
        old = app.tutorial.scenario
        self.frame(w, clock, app)
        self.frame(w, clock, app, ('esc',), ('esc',))
        self.frame(w, clock, app)
        app.tutorial_focus = 'retry_step'
        self.frame(w, clock, app, ('enter',), ('enter',))
        with patch('tank_game.tutorial.make_tutorial_scenario', side_effect=ValueError('bad map')):
            self.frame(w, clock, app)
        self.assertIs(app.tutorial.scenario, old)
        self.assertEqual(app.tutorial.phase, 'error')
        self.assertEqual(app.ui.screen, 'tutorial')

    def test_advance_cannot_carry_fire_or_held_click_to_shooting_lesson(self):
        w, clock, app = self.enter_tutorial()
        self.select_step(w, clock, app, 2)
        app.tutorial.phase = 'success'
        self.frame(w, clock, app, ('enter',), ('enter', 'space', 'mouse-left'))
        self.frame(w, clock, app, held=('space', 'mouse-left'))
        self.assertEqual(app.tutorial.step_number, 3)
        self.frame(w, clock, app, ('space',), ('space', 'mouse-left'))
        self.assertFalse(app.tutorial.shot_fired)
        self.frame(w, clock, app)
        self.assertFalse(app.tutorial.shot_fired)
        self.frame(w, clock, app, ('space',), ('space',))
        self.assertTrue(app.tutorial.shot_fired)


    def test_first_use_recommends_tutorial_without_gating_start_or_random(self):
        w, clock, app = self.make_app()
        self.assertEqual(app.ui.focus, 'tutorial')
        self.assertIn('start', app.ui.rows())
        self.assertIn('map', app.ui.rows())
        self.assertTrue(app.ui.selection.effective()[2])
        self.frame(w, clock, app, ('enter',), ('enter',))
        self.assertEqual(app.ui.screen, 'menu')
        self.frame(w, clock, app)
        self.assertEqual(app.ui.screen, 'tutorial')

    def test_skip_or_direct_start_suppresses_refocus_only_this_run(self):
        w, clock, app = self.enter_tutorial()
        app._skip_tutorial()
        self.frame(w, clock, app)
        self.assertFalse(app.ui.tutorial_recommended_this_run)
        self.assertFalse(app.ui.tutorial_completed)
        self.assertEqual(app.ui.focus, 'start')
        app.ui.selection.bot_enabled = False
        self.frame(w, clock, app, ('enter',))
        self.frame(w, clock, app, dt=.13)
        self.assertEqual(app.ui.screen, 'playing')
        self.assertFalse(app.ui.tutorial_recommended_this_run)

    def test_completion_is_saved_before_returning_to_menu(self):
        from tank_game.tutorial_progress import load_completed
        w, clock, app = self.enter_tutorial()
        self.select_step(w, clock, app, 5)
        self.frame(w, clock, app, ('space',))
        for _ in range(850):
            self.frame(w, clock, app)
        self.assertEqual(app.tutorial.phase, 'complete')
        self.assertEqual(app.ui.screen, 'tutorial')
        self.assertTrue(app.ui.tutorial_completed)
        self.assertTrue(load_completed(app.tutorial_progress_path))
        _, _, restarted = self.make_app(tutorial_progress_path=app.tutorial_progress_path)
        self.assertTrue(restarted.ui.tutorial_completed)
        self.assertEqual(restarted.ui.focus, 'start')

    def test_save_failure_keeps_in_memory_completion_and_game_available(self):
        w, clock, app = self.enter_tutorial()
        self.select_step(w, clock, app, 5)
        with patch('tank_game.app.save_completed', return_value=False):
            self.frame(w, clock, app, ('space',))
            for _ in range(850):
                self.frame(w, clock, app)
        self.assertTrue(app.ui.tutorial_completed)
        app._skip_tutorial()
        self.assertEqual(app.ui.focus, 'start')
        self.assertIn('start', app.ui.rows())

    def test_abandoned_replay_preserves_completion(self):
        from tank_game.tutorial_progress import save_completed
        w, clock, app = self.make_app()
        save_completed(app.tutorial_progress_path)
        before = app.tutorial_progress_path.read_bytes()
        app.ui.tutorial_completed = True
        app._start_tutorial()
        self.frame(w, clock, app)
        app._skip_tutorial()
        self.assertTrue(app.ui.tutorial_completed)
        self.assertEqual(app.tutorial_progress_path.read_bytes(), before)

    def test_skip_click_consumed_once_and_keyboard_skip_available(self):
        from tank_game.tutorial_rendering import skip_button_bounds
        w, clock, app = self.enter_tutorial()
        x, y, width, height = skip_button_bounds()
        w.mouse_x, w.mouse_y = x+width/2, y+height/2
        self.frame(w, clock, app, ('mouse-left',), ('mouse-left',))
        self.assertEqual(app.ui.screen, 'tutorial')
        self.frame(w, clock, app)
        self.assertEqual(app.ui.screen, 'menu')
        self.frame(w, clock, app, ('mouse-left',), ('mouse-left',))
        self.assertEqual(app.ui.screen, 'menu')
        self.assertIsNone(app.world)
        self.frame(w, clock, app)
        app._start_tutorial()
        self.frame(w, clock, app)
        self.frame(w, clock, app, ('esc',), ('esc',))
        self.frame(w, clock, app)
        self.frame(w, clock, app, ('down',))
        self.frame(w, clock, app, ('down',))
        self.frame(w, clock, app, ('enter',), ('enter',))
        self.frame(w, clock, app)
        self.assertEqual(app.ui.screen, 'menu')

    def test_celebration_runs_once_without_advancing_world_and_freezes_on_pause(self):
        w, clock, app = self.enter_tutorial()
        goal_around_current(app.tutorial)
        for _ in range(15):
            self.frame(w, clock, app)
        self.assertEqual(app.tutorial.phase, 'success')
        self.assertEqual(app.tutorial_celebration_age, 0)
        before = app.scene
        for _ in range(10):
            self.frame(w, clock, app)
        age = app.tutorial_celebration_age
        self.assertGreater(age, 0)
        self.assertEqual(app.scene, before)
        self.frame(w, clock, app, ('esc',), ('esc',))
        paused_age = app.tutorial_celebration_age
        self.frame(w, clock, app, dt=30)
        self.assertEqual(app.tutorial_celebration_age, paused_age)
        self.frame(w, clock, app, ('esc',), ('esc',))
        self.frame(w, clock, app)
        for _ in range(90):
            self.frame(w, clock, app)
        self.assertGreater(app.tutorial_celebration_age, .7)
        self.assertEqual(app.scene, before)


    def test_clickable_tutorial_and_returned_menu_both_show_cursor(self):
        w, _clock, app = self.enter_tutorial()
        self.assertTrue(w.cursor_visible)
        app._skip_tutorial()
        self.assertTrue(w.cursor_visible)


    def test_step_four_success_does_not_save_and_held_fire_cannot_start_five(self):
        w, clock, app = self.enter_tutorial()
        self.select_step(w, clock, app, 4)
        self.frame(w, clock, app, ('space',))
        for _ in range(310):
            self.frame(w, clock, app)
        self.assertEqual(app.tutorial.phase, 'success')
        self.assertFalse(app.ui.tutorial_completed)
        self.assertFalse(app.tutorial_progress_path.exists())
        self.frame(w, clock, app, ('enter',), ('enter','space'))
        self.frame(w, clock, app, held=('space',))
        self.assertEqual(app.tutorial.step_number, 5)
        self.frame(w, clock, app, ('space',), ('space',))
        self.assertFalse(app.tutorial.ammo_started)
        self.frame(w, clock, app)
        self.frame(w, clock, app, ('space',))
        self.assertTrue(app.tutorial.ammo_started)

    def test_ammo_pause_freezes_fill_return_and_highlight_retry_resets(self):
        for ticks in (8, 605):
            with self.subTest(ticks=ticks):
                w, clock, app = self.enter_tutorial()
                self.select_step(w, clock, app, 5)
                self.frame(w, clock, app, ('space',))
                for _ in range(ticks):
                    self.frame(w, clock, app)
                self.frame(w, clock, app, ('esc',), ('esc',))
                before = app.scene
                count, flash = app.tutorial.ammo_shots_fired, app.tutorial.ammo_flash_seconds
                self.frame(w, clock, app, dt=60)
                self.assertEqual(app.scene, before)
                self.assertEqual(app.tutorial.ammo_shots_fired, count)
                self.assertEqual(app.tutorial.ammo_flash_seconds, flash)
                app.tutorial_focus = 'retry_step'
                self.frame(w, clock, app, ('enter',), ('enter','space'))
                self.frame(w, clock, app, held=('space',))
                self.assertEqual(app.tutorial.ammo_shots_fired, 0)
                self.assertFalse(app.tutorial.ammo_started)
                self.frame(w, clock, app, ('space',), ('space',))
                self.assertFalse(app.tutorial.ammo_started)
                self.frame(w, clock, app)
                self.frame(w, clock, app, ('space',))
                self.assertTrue(app.tutorial.ammo_started)
                app._skip_tutorial()
                self.assertFalse(app.tutorial_progress_path.exists())
                self.assertEqual(app.ui.focus, 'start')


    def test_legacy_save_survives_skipping_unfinished_fifth_lesson(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'progress.json'
            legacy = '{"tutorial_version": 1, "completed": true}'
            path.write_text(legacy)
            w, clock, app = self.enter_tutorial(tutorial_progress_path=path)
            self.assertFalse(app.ui.tutorial_completed)
            self.select_step(w, clock, app, 5)
            self.frame(w, clock, app, ('space',))
            for _ in range(30):
                self.frame(w, clock, app)
            app._skip_tutorial()
            self.assertEqual(path.read_text(), legacy)
            self.assertFalse(app.ui.tutorial_completed)

    def test_custom_fifth_fire_does_not_require_space(self):
        import json

        from tank_game.keymap import DEFAULT_KEYMAP_PATH
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'keys.json'
            data = json.loads(DEFAULT_KEYMAP_PATH.read_text())
            data['bindings']['fire'] = ['F1']
            path.write_text(json.dumps(data))
            with patch.object(TutorialWindow, 'KEY_F1', 'f1', create=True):
                w, clock, app = self.enter_tutorial(keymap_path=path)
                self.select_step(w, clock, app, 5)
                self.frame(w, clock, app, ('space',))
                self.assertFalse(app.tutorial.ammo_started)
                self.frame(w, clock, app)
                self.frame(w, clock, app, ('f1',), ('f1',))
                self.assertTrue(app.tutorial.ammo_started)
                for _ in range(850):
                    self.frame(w, clock, app, held=('f1',))
                self.assertEqual(app.tutorial.ammo_shots_fired, 5)
                self.assertEqual(app.tutorial.phase, 'complete')
