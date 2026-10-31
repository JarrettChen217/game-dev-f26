"""Mouse gestures enter the same real app operations as keyboard menus."""
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from tank_game.agents import AgentScheduler, InlineWorker
from tank_game.strategies import make_policy
from tank_game.ui_layout import layout_controls
from tank_game.window_state import WindowSnapshot
from tests import test_tutorial_app as helpers


class MouseAppTests(unittest.TestCase):
    make_app = helpers.TutorialAppTests.make_app
    frame = helpers.TutorialAppTests.frame
    enter_tutorial = helpers.TutorialAppTests.enter_tutorial
    select_step = helpers.TutorialAppTests.select_step

    def controls(self, app):
        return layout_controls(app.ui, tutorial_phase=app.tutorial.phase if app.tutorial else None,
                               tutorial_paused=app.ui.screen == 'tutorial_pause')

    def point(self, window, app, target):
        c = next(c for c in self.controls(app) if c.id == target)
        x, y, width, height = c.rect
        window.mouse_x, window.mouse_y = x+width//2, y+height//2

    def click(self, w, clock, app, target):
        self.frame(w, clock, app)
        self.point(w, app, target)
        self.frame(w, clock, app, ('mouse-left',), ('mouse-left',))
        self.frame(w, clock, app)

    def test_main_concrete_choices_bot_recovery_and_help_back(self):
        w, clock, app = self.make_app()
        self.click(w, clock, app, 'strength:hard')
        self.assertEqual(app.ui.selection.strategy, 'hard')
        self.click(w, clock, app, 'map:fixed')
        self.assertFalse(app.ui.selection.random_map)
        self.click(w, clock, app, 'bot')
        self.assertFalse(app.ui.selection.bot_enabled)
        self.click(w, clock, app, 'bot')
        self.assertEqual((app.ui.selection.strategy, app.ui.selection.random_map), ('hard', False))
        self.click(w, clock, app, 'help')
        self.assertEqual(app.ui.screen, 'help')
        self.frame(w, clock, app)
        self.frame(w, clock, app, ('enter',), ('enter',))
        self.frame(w, clock, app)
        self.assertEqual((app.ui.screen, app.ui.focus), ('menu', 'help'))
        self.assertTrue(w.cursor_visible)

    def test_all_tutorial_states_click_through_existing_operations(self):
        w, clock, app = self.enter_tutorial()
        app.tutorial.phase = 'success'
        self.click(w, clock, app, 'advance')
        self.assertEqual(app.tutorial.step_number, 2)
        self.frame(w, clock, app, ('esc',), ('esc',))
        self.frame(w, clock, app)
        self.click(w, clock, app, 'resume')
        self.assertEqual(app.ui.screen, 'tutorial')
        app.tutorial.phase = 'error'
        self.click(w, clock, app, 'retry_step')
        self.assertEqual((app.tutorial.phase, app.tutorial.step_number), ('active', 2))
        self.click(w, clock, app, 'skip_tutorial')
        self.assertEqual(app.ui.screen, 'menu')
        self.assertFalse(app.ui.tutorial_completed)
        app._start_tutorial(); self.frame(w, clock, app)
        app.tutorial.phase = 'complete'
        self.click(w, clock, app, 'return_menu')
        self.assertEqual((app.ui.screen, app.ui.focus), ('menu', 'start'))

    def test_release_inside_only_and_static_pointer_does_not_steal_focus(self):
        w, clock, app = self.make_app()
        self.frame(w, clock, app)
        self.point(w, app, 'help'); self.frame(w, clock, app)
        self.assertEqual(app.ui.focus, 'help')
        self.frame(w, clock, app, ('up',))
        self.frame(w, clock, app)
        self.assertEqual(app.ui.focus, 'start')
        self.point(w, app, 'quit')
        self.frame(w, clock, app, ('mouse-left',), ('mouse-left',))
        self.assertFalse(w.exited)
        w.mouse_x, w.mouse_y = 0, 0
        self.frame(w, clock, app)
        self.assertFalse(w.exited)
        self.click(w, clock, app, 'quit')
        self.assertTrue(w.exited)

    def test_native_change_cancels_keyboard_and_mouse_quit(self):
        for source in ('enter', 'mouse-left'):
            w, clock, app = self.make_app()
            snapshot = [WindowSnapshot(True, ('native', 0), True)]
            app.window_observer = SimpleNamespace(sample=lambda _, snapshot=snapshot: snapshot[0])
            app.ui.focus = 'quit'
            self.frame(w, clock, app)
            self.point(w, app, 'quit')
            self.frame(w, clock, app, (source,), (source,))
            snapshot[0] = replace(snapshot[0], viewport_token=('native', 1))
            self.frame(w, clock, app)
            self.assertFalse(w.exited, source)
            self.frame(w, clock, app)
            self.click(w, clock, app, 'quit')
            self.assertTrue(w.exited)

    def test_overlay_origin_change_cancels_held_keyboard_quit(self):
        w, clock, app = self.make_app()
        app.ui.selection.bot_enabled = False
        self.click(w, clock, app, 'start')
        self.frame(w, clock, app, dt=.2); self.frame(w, clock, app)
        self.frame(w, clock, app, ('esc',), ('esc',)); self.frame(w, clock, app)
        app.ui.focus = 'quit'
        self.frame(w, clock, app, ('enter',), ('enter',))
        app.ui.inspection_visible = True
        self.frame(w, clock, app)
        self.assertFalse(w.exited)
        self.assertEqual(app.ui.screen, 'pause')

    def test_held_left_mouse_gates_gameplay_after_keyboard_start(self):
        w, clock, app = self.make_app()
        app.ui.selection.bot_enabled = False
        app.ui.focus = 'start'
        self.frame(w, clock, app, ('enter', 'mouse-left'), ('enter', 'mouse-left'))
        self.frame(w, clock, app, held=('mouse-left',), dt=.2)
        before = app.scene['tanks'][0]
        self.frame(w, clock, app, held=('mouse-left',))
        self.frame(w, clock, app, held=('mouse-left', 'up'))
        self.assertEqual(app.scene['tanks'][0], before)
        self.frame(w, clock, app)
        self.frame(w, clock, app, held=('up',))
        self.assertNotEqual((app.scene['tanks'][0]['x'],app.scene['tanks'][0]['y']),
                            (before['x'],before['y']))

    def test_start_pause_resume_retry_menu_and_cursor(self):
        w, clock, app = self.make_app()
        app.ui.selection.bot_enabled = False
        self.click(w, clock, app, 'start')
        self.frame(w, clock, app, dt=.2)
        self.frame(w, clock, app)
        self.assertEqual(app.ui.screen, 'playing')
        self.assertFalse(w.cursor_visible)
        self.frame(w, clock, app, ('esc',), ('esc',))
        self.frame(w, clock, app)
        scene = app.scene
        self.frame(w, clock, app, dt=60)
        self.assertEqual(app.scene, scene)
        self.assertTrue(w.cursor_visible)

        self.click(w, clock, app, 'resume')
        self.assertFalse(w.cursor_visible)
        self.frame(w, clock, app)
        self.frame(w, clock, app, ('esc',), ('esc',)); self.frame(w, clock, app)
        self.click(w, clock, app, 'retry')
        self.assertEqual(app.scene['round_id'], 2)
        self.assertFalse(app.scene['bullets'])
        self.frame(w, clock, app)
        self.frame(w, clock, app, ('esc',), ('esc',)); self.frame(w, clock, app)
        self.click(w, clock, app, 'menu')
        self.assertEqual((app.ui.screen, app.ui.focus), ('menu', 'start'))
        self.assertIsNone(app.world)
        self.assertTrue(w.cursor_visible)

    def test_each_result_action_uses_the_real_session_lifecycle(self):
        for random_map in (False, True):
            for operation in ('retry', 'menu', 'quit', *(('next_map',) if random_map else ())):
                with self.subTest(random_map=random_map, operation=operation):
                    w, clock, app = self.make_app(scheduler_factory=lambda:
                        AgentScheduler(InlineWorker(make_policy('simple'))))
                    app.ui.selection.random_map = random_map
                    self.click(w, clock, app, 'start')
                    self.frame(w, clock, app, dt=.2); self.frame(w, clock, app)
                    # Explicit terminal fixture; action replacement uses real GameSession/World.
                    app.world._packet['render'][14] = 1
                    app.scene = app.world.observe('tank-1')
                    self.frame(w, clock, app)
                    self.click(w, clock, app, operation)
                    if operation == 'quit':
                        self.assertTrue(w.exited)
                    elif operation == 'menu':
                        self.assertIsNone(app.world)
                        self.assertEqual(app.ui.focus, 'start')
                    else:
                        self.assertEqual(app.scene['round_id'], 2)
                        self.assertEqual(app.scene['observation_tick'], 0)
                        self.assertEqual(app.ui.screen, 'playing')

    def test_failed_pointer_new_map_preserves_scene_and_retry_remains_usable(self):
        w, clock, app = self.make_app(scheduler_factory=lambda:
            AgentScheduler(InlineWorker(make_policy('simple'))))
        self.click(w, clock, app, 'start')
        self.frame(w, clock, app, dt=.2); self.frame(w, clock, app)
        app.world._packet['render'][14] = 1
        app.scene = app.world.observe('tank-1')
        self.frame(w, clock, app)
        world = app.world
        with patch.object(world, 'restart', side_effect=OSError('mouse test failure')):
            self.click(w, clock, app, 'next_map')
        self.assertIs(app.world, world)
        self.assertEqual(app.ui.screen, 'results')
        self.assertIsNotNone(app.ui.error)
        self.click(w, clock, app, 'retry')
        self.assertEqual(app.ui.screen, 'playing')
        self.assertIsNone(app.ui.error)

    def test_setting_label_only_focuses_and_selected_choice_is_idempotent(self):
        w, clock, app = self.make_app()
        self.click(w, clock, app, 'strength:label')
        self.assertEqual(app.ui.focus, 'strength')
        self.assertEqual(app.ui.selection.strategy, 'simple')
        self.click(w, clock, app, 'strength:simple')
        self.assertEqual(app.ui.selection.strategy, 'simple')

    def test_fifth_lesson_pointer_confirmation_does_not_advance_paused_burst(self):
        w, clock, app = self.enter_tutorial()
        self.select_step(w, clock, app, 5)
        self.frame(w, clock, app, ('space',))
        self.frame(w, clock, app, ('esc',), ('esc',)); self.frame(w, clock, app)
        before = app.scene
        self.point(w, app, 'resume')
        self.frame(w, clock, app, ('mouse-left',), ('mouse-left',), dt=60)
        self.frame(w, clock, app, held=('mouse-left',), dt=60)
        self.assertEqual(app.scene, before)
        self.frame(w, clock, app)
        self.assertEqual(app.ui.screen, 'tutorial')
        self.assertEqual(app.scene, before)
