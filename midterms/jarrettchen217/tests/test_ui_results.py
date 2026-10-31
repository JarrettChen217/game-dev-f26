"""Result commands use actual terminal worlds and preserve failed maps."""
import unittest
from unittest.mock import patch

from tank_game.agents import AgentScheduler, InlineWorker
from tank_game.app import DrivingApp
from tank_game.random_maps import GenerationError
from tank_game.random_rounds import RandomRoundSession
from tank_game.strategies import make_policy
from tank_game.ui_rendering import draw_results
from tests.test_driving_app import confirm_result
from tests.test_round_lifecycle import hit_world
from tests.test_ui_rendering import FakeWindow


class ResultsTests(unittest.TestCase):
    def test_space_is_inert_and_enter_confirms_only_on_release(self):
        window, app, session = self.make_app()
        before = app.scene.copy()
        old = session.record
        window.pressed = {'space'}
        app.update()
        self.assertEqual(app.scene, before)
        window.pressed = {'enter'}
        window.held = {'enter'}
        app.update()
        self.assertEqual(app.scene, before)
        app.draw()
        self.assertTrue(any(rect[-1] == 3 for rect in window.rectangles))
        window.pressed = {'down', 'n', 'space'}
        for _ in range(20):
            app.update()
        self.assertEqual(app.scene, before)
        self.assertEqual(app.ui.focus, 'retry')
        window.pressed.clear()
        window.held.clear()
        app.update()
        self.assertEqual(app.scene['round_id'], 2)
        self.assertEqual(app.scene['observation_tick'], 0)
        self.assertEqual(session.record, old)

    def test_escape_cancels_held_retry_and_focuses_quit_without_replaying(self):
        window, app, _session = self.make_app()
        world = app.world
        window.pressed = {'enter'}
        window.held = {'enter'}
        app.update()
        window.pressed = {'esc'}
        app.update()
        self.assertEqual(app.ui.screen, 'results')
        self.assertEqual(app.ui.focus, 'quit')
        self.assertEqual(world.observe('tank-1')['round_id'], 1)
        window.pressed.clear()
        window.held.clear()
        app.update()
        self.assertIs(app.world, world)
        self.assertFalse(window.exited)

    def test_selected_new_map_and_menu_execute_once_after_enter_release(self):
        for steps, operation in ((1, 'next_map'), (2, 'menu')):
            with self.subTest(operation=operation):
                window, app, session = self.make_app()
                old, world = session.record, app.world
                for _ in range(steps):
                    window.pressed = {'down'}
                    app.update()
                window.pressed = {'enter'}
                window.held = {'enter'}
                app.update()
                self.assertIs(app.world, world)
                self.assertEqual(session.record, old)
                self.assertEqual(app.ui.pending_result, operation)
                window.pressed.clear()
                window.held.clear()
                app.update()
                if operation == 'next_map':
                    self.assertNotEqual(session.record.layout_id, old.layout_id)
                    self.assertEqual(app.scene['round_id'], 2)
                    self.assertEqual(app.scene['observation_tick'], 0)
                else:
                    self.assertIsNone(app.world)
                    self.assertEqual(app.ui.screen, 'menu')
                    app.update()
                    self.assertIsNone(app.world)

    def make_app(self):
        window = FakeWindow()
        session = RandomRoundSession(17, round_limit=1/60)
        app = DrivingApp(window, random_session=session, clock=window.clock,
                         scheduler_factory=lambda: AgentScheduler(InlineWorker(make_policy('simple'))))
        self.addCleanup(app.close)
        app.update()
        return window, app, session

    def test_menu_action_closes_worker_once_and_preserves_choices(self):
        window, app, _session = self.make_app()
        self.assertEqual(app.ui.screen, 'results')
        with patch.object(app.scheduler, 'close', wraps=app.scheduler.close) as close:
            window.pressed = {'esc', 'space', 'n', 'enter'}
            app.update()
            self.assertEqual(close.call_count, 0)
            self.assertEqual(app.ui.focus, 'quit')
            window.pressed.clear()
            app.update()
            app.ui.focus = 'menu'
            confirm_result(window, app)
            self.assertEqual(close.call_count, 1)
        self.assertFalse(window.exited)
        self.assertIsNone(app.world)
        self.assertIsNone(app.scheduler)
        self.assertEqual(app.ui.screen, 'menu')
        self.assertEqual(app.ui.selection.effective(), (True,'simple',True))

    def test_failed_new_map_retains_world_seed_and_decision_state(self):
        window, app, session = self.make_app()
        world, old, scheduler = app.world, session.record, app.scheduler
        with patch('tank_game.random_rounds.generate_random_map',
                   side_effect=GenerationError(18, ('forced failure',))):
            window.pressed = {'n'}
            app.update()
        self.assertIs(app.world, world)
        self.assertIs(app.scheduler, scheduler)
        self.assertEqual(session.record, old)
        self.assertEqual(app.ui.screen, 'results')
        self.assertIn('forced failure', app.ui.error)
        confirm_result(window, app)
        self.assertEqual(session.record, old)
        self.assertEqual(app.scene['round_id'], 2)
        self.assertEqual(app.scene['observation_tick'], 0)
        self.assertIsNot(app.scheduler, scheduler)

    def test_result_enter_retry_and_real_labels_use_public_result(self):
        window, app, _session = self.make_app()
        before = app.scene['round_id']
        for result, want in (('tank-1','You win'), ('tank-2','Bot wins'), ('draw','Draw')):
            with self.subTest(result=result):
                window.texts.clear()
                scene = dict(app.scene, duel=dict(app.scene['duel'], result=result))
                draw_results(window, scene, app.ui, strategy='simple', seed=17,
                             keymap=app.keymap, origin=(204,40), now=0)
                self.assertIn(want, ' '.join(t[2] for t in window.texts))
        confirm_result(window, app)
        self.assertEqual(app.scene['round_id'], before+1)
        self.assertEqual(app.ui.screen, 'playing')

    def test_explosion_finishes_before_practice_results(self):
        window = FakeWindow()
        app = DrivingApp(window, hit_world(), clock=window.clock)
        self.addCleanup(app.close)
        window.pressed = {'enter', 'space'}
        app.update()
        self.assertEqual(app.ui.screen, 'dying')
        self.assertEqual(app.scene['round_id'], 1)
        window.pressed.clear()
        for _ in range(22):
            app.update()
        self.assertEqual(app.ui.screen, 'results')
        app.draw()
        self.assertIn('Game over', ' '.join(t[2] for t in window.texts))
        self.assertNotIn('New map', ' '.join(t[2] for t in window.texts))

    def test_menu_owned_replay_and_return_start_reset_workers_and_held_keys(self):
        window = FakeWindow()
        app = DrivingApp(window, menu=True, clock=window.clock,
                         scheduler_factory=lambda: AgentScheduler(InlineWorker(make_policy('simple'))))
        self.addCleanup(app.close)
        app.ui.focus = 'start'
        app.ui.selection.random_map = False
        window.pressed = {'enter'}
        app.update()
        window.pressed.clear()
        for _ in range(10):
            app.update()
        self.assertEqual(app.ui.screen, 'playing')
        old = app.scheduler
        # Synthetic terminal snapshot: this test exercises host UI, not physics.
        app.world._packet['render'][14] = 1
        for _ in range(24):
            app.update()
        self.assertEqual(app.ui.screen, 'results')
        app.ui.inspection_visible = True
        window.held = {'enter', 'w', 'space'}
        window.pressed = {'enter'}
        app.update()
        self.assertEqual(app.ui.screen, 'results')
        window.held.discard('enter')
        window.pressed.clear()
        app.update()
        self.assertEqual(app.scene['observation_tick'], 0)
        self.assertIsNot(app.scheduler, old)
        self.assertIsNone(old.worker.result)
        self.assertTrue(app.ui.inspection_visible)
        before = app.scene['tanks'][0]
        window.pressed.clear()
        app.update()
        self.assertEqual(app.scene['tanks'][0], before)
        self.assertEqual(app.scene['bullets'], [])
        window.held.clear()
        # Synthetic terminal snapshot: this test exercises host UI, not physics.
        app.world._packet['render'][14] = 1
        for _ in range(24):
            app.update()
        app.ui.focus = 'menu'
        confirm_result(window, app)
        self.assertEqual(app.ui.screen, 'menu')
        window.pressed = {'enter'}
        app.update()
        window.pressed.clear()
        for _ in range(10):
            app.update()
        self.assertEqual(app.ui.screen, 'playing')
        self.assertFalse(app.ui.inspection_visible)
