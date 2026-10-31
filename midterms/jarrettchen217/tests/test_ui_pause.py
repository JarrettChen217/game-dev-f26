"""Real adapter pause/quit boundaries; synthetic keys are not human play."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tank_game.agents import AgentScheduler, InlineWorker, ProcessWorker
from tank_game.app import DrivingApp
from tank_game.keymap import DEFAULT_KEYMAP_PATH
from tank_game.random_maps import GenerationError
from tank_game.random_rounds import RandomRoundSession
from tank_game.strategies import make_policy
from tank_game.world import World
from tests.test_realtime import Clock
from tests.test_round_lifecycle import hit_world
from tests.test_ui_rendering import FakeWindow


class PauseTests(unittest.TestCase):
    def make_app(self, **kwargs):
        w, clock = FakeWindow(), Clock()
        app = DrivingApp(w, clock=clock, **kwargs)
        self.addCleanup(app.close)
        if kwargs.get('menu'):
            app.ui.focus = 'start'
        return w, clock, app

    def frame(self, w, clock, app, pressed=(), held=(), dt=1/60):
        w.pressed, w.held = set(pressed), set(held)
        clock.now += dt
        app.update()

    def test_pause_freezes_and_esc_resume_has_no_time_or_input_leak(self):
        w, clock, app = self.make_app(world=World(duel=True),
                                    scheduler=AgentScheduler(InlineWorker(make_policy('simple'))))
        self.frame(w, clock, app, held=('w',))
        before, scheduler = app.scene, app.scheduler
        self.frame(w, clock, app, ('esc',), ('esc', 'w', 'space'))
        self.assertEqual(app.ui.screen, 'pause')
        self.assertEqual(app.scene, before)
        self.assertFalse(w.exited)
        self.frame(w, clock, app, ('esc',), ('esc',), dt=60)
        self.assertEqual(app.ui.screen, 'pause')
        self.frame(w, clock, app)
        app.ui.focus = 'quit'
        self.frame(w, clock, app, ('esc',), ('esc',))
        app.draw()
        self.assertEqual(app.ui.focus, 'resume')
        self.assertTrue(any(r[-1] == 3 for r in w.rectangles))
        self.assertEqual(app.scene, before)
        self.frame(w, clock, app, held=('w', 'space'), dt=30)
        self.assertEqual(app.ui.screen, 'playing')
        self.assertEqual(app.scene, before)
        self.assertIs(app.scheduler, scheduler)
        self.frame(w, clock, app, ('space',), ('w', 'space'))
        self.assertEqual(app.scene['tanks'], before['tanks'])
        self.assertEqual(app.scene['bullets'], before['bullets'])
        self.frame(w, clock, app)
        tick = app.scene['observation_tick']
        self.frame(w, clock, app, held=('w',))
        self.assertEqual(app.scene['observation_tick'], tick+1)

    def test_start_and_results_require_two_separate_esc_presses_then_release(self):
        for menu in (True, False):
            with self.subTest(menu=menu):
                w, clock, app = self.make_app(menu=True) if menu else self.make_app(world=hit_world())
                if not menu:
                    for _ in range(24):
                        self.frame(w, clock, app)
                app.ui.focus = 'quit'  # already focused still needs two presses
                before = app.scene
                self.frame(w, clock, app, ('esc',), ('esc',))
                self.assertFalse(w.exited)
                self.frame(w, clock, app, ('esc',), ('esc',), dt=1)
                self.assertFalse(w.exited)
                self.frame(w, clock, app)
                self.assertFalse(w.exited)
                self.frame(w, clock, app, ('esc', 'enter'), ('esc', 'enter'))
                app.draw()
                self.assertTrue(any(r[-1] == 3 for r in w.rectangles))
                self.frame(w, clock, app, held=('esc',), dt=1)
                self.assertFalse(w.exited)  # Enter release cannot release Esc confirmation
                self.assertEqual(app.scene, before)
                self.frame(w, clock, app)
                self.assertTrue(w.exited)

    def test_navigation_cancels_quit_arming_and_enter_quit_waits_for_release(self):
        w, clock, app = self.make_app(menu=True)
        self.frame(w, clock, app, ('esc',), ('esc',))
        self.frame(w, clock, app)
        self.frame(w, clock, app, ('up',))
        self.frame(w, clock, app, ('esc',), ('esc',))
        self.frame(w, clock, app)
        self.assertFalse(w.exited)
        self.frame(w, clock, app, ('enter',), ('enter',))
        self.assertFalse(w.exited)
        self.frame(w, clock, app)
        self.assertTrue(w.exited)

    def test_custom_quit_cannot_replace_an_enter_confirmation_key(self):
        data = json.loads(DEFAULT_KEYMAP_PATH.read_text())
        data['bindings']['quit'] = ['Q']
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'keys.json'
            path.write_text(json.dumps(data))
            with patch.object(FakeWindow, 'KEY_Q', 'q', create=True):
                w, clock, app = self.make_app(menu=True, keymap_path=path)
                app.ui.focus = 'quit'
                self.frame(w, clock, app, ('enter',), ('enter',))
                self.frame(w, clock, app, ('q',), ('enter', 'q'))
                self.assertEqual(app.ui.pending_result, 'quit')
                self.assertFalse(w.exited)
                self.frame(w, clock, app, held=('q',))
                self.assertTrue(w.exited)  # original Enter release owns this action

                w, clock, app = self.make_app(keymap_path=path)
                self.frame(w, clock, app, ('esc',), ('esc',))
                self.frame(w, clock, app)
                for _ in range(2):
                    self.frame(w, clock, app, ('q',), ('q',))
                    self.frame(w, clock, app)
                self.assertEqual(app.ui.screen, 'pause')
                self.assertEqual(app.ui.focus, 'resume')
                self.assertFalse(w.exited)

    def test_pause_esc_cancels_pending_enter_quit_and_resumes(self):
        w, clock, app = self.make_app()
        self.frame(w, clock, app, ('esc',), ('esc',))
        self.frame(w, clock, app)
        app.ui.focus = 'quit'
        self.frame(w, clock, app, ('enter',), ('enter',))
        self.frame(w, clock, app, ('esc',), ('esc', 'enter'))
        self.frame(w, clock, app, held=('enter',))
        self.assertEqual(app.ui.screen, 'playing')
        self.assertFalse(w.exited)

    def test_pause_replay_map_failure_and_main_menu(self):
        for operation in ('retry', 'next_map', 'menu'):
            with self.subTest(operation=operation):
                session = RandomRoundSession(17)
                w, clock, app = self.make_app(random_session=session,
                    scheduler_factory=lambda: AgentScheduler(InlineWorker(make_policy('simple'))))
                self.frame(w, clock, app)
                self.frame(w, clock, app, ('esc',), ('esc',))
                self.frame(w, clock, app)
                world, record, old = app.world, session.record, app.scheduler
                app.ui.focus = operation
                if operation == 'next_map':
                    self.frame(w, clock, app, ('enter',), ('enter',))
                    with patch('tank_game.random_rounds.generate_random_map',
                               side_effect=GenerationError(18, ('pause fixture',))):
                        self.frame(w, clock, app)
                    self.assertEqual(app.ui.screen, 'pause')
                    self.assertIs(app.scheduler, old)
                    self.assertIs(app.world, world)
                    self.assertEqual(session.record, record)
                    self.assertIn('pause fixture', app.ui.error)
                self.frame(w, clock, app, ('enter',), ('enter',))
                self.assertIs(app.world, world)
                self.frame(w, clock, app)
                if operation == 'menu':
                    self.assertIsNone(app.world)
                    self.assertEqual(app.ui.screen, 'menu')
                else:
                    self.assertEqual(app.ui.screen, 'playing')
                    self.assertEqual(app.scene['round_id'], 2)
                    self.assertEqual(app.scene['observation_tick'], 0)
                    self.assertIsNot(app.scheduler, old)
                    self.assertEqual(session.record == record, operation == 'retry')

    def test_dying_pause_preserves_effect_progress(self):
        w, clock, app = self.make_app(world=hit_world())
        self.frame(w, clock, app)
        before = app.scene
        self.frame(w, clock, app, ('esc',), ('esc',))
        self.frame(w, clock, app, dt=10)
        self.assertEqual(app.scene, before)
        self.frame(w, clock, app, ('esc',), ('esc',))
        self.frame(w, clock, app)
        self.assertEqual(app.ui.screen, 'dying')
        for _ in range(24):
            self.frame(w, clock, app)
        self.assertEqual(app.ui.screen, 'results')
        self.assertNotIn('resume', app.ui.rows())

    def test_active_round_replacement_requires_explicit_host_opt_in(self):
        world = World()
        self.assertFalse(world.restart())
        self.assertTrue(world.restart(allow_active=True))
        self.assertEqual(world.observe('tank-1')['round_id'], 2)

    def test_injected_worker_without_factory_cannot_silently_replay_active_round(self):
        scheduler = AgentScheduler(InlineWorker(make_policy('simple')))
        w, clock, app = self.make_app(world=World(duel=True), scheduler=scheduler)
        self.frame(w, clock, app, ('esc',), ('esc',))
        self.frame(w, clock, app)
        before = app.scene
        app.ui.focus = 'retry'
        self.frame(w, clock, app, ('enter',), ('enter',))
        self.frame(w, clock, app)
        self.assertEqual(app.ui.screen, 'pause')
        self.assertEqual(app.scene, before)
        self.assertIs(app.scheduler, scheduler)
        self.assertIn('scheduler_factory', app.ui.error)

    def test_scheduler_pause_discards_old_decision_without_replacing_policy(self):
        scheduler = AgentScheduler(InlineWorker(make_policy('simple')))
        scene = World(duel=True).observe('tank-2')
        scheduler.worker.submit(scene)
        policy = scheduler.worker.policy
        scheduler.pause(scene)
        self.assertIsNone(scheduler.worker.poll())
        self.assertIs(scheduler.worker.policy, policy)
        self.assertFalse(scheduler.request(scene)['fire'])

    def test_process_response_ready_after_long_pause_is_discarded_without_disabling_bot(self):
        worker = ProcessWorker(make_policy('simple'), timeout=2)
        self.addCleanup(worker.close)
        scene = World(duel=True).observe('tank-2')
        worker.submit(scene)
        worker.discard_pending()
        self.assertTrue(worker.connection.poll(3), 'real process must respond')
        original, started = worker.pending
        worker.pending = original, started-60  # emulate late UI polling after a long pause
        self.assertIsNone(worker.poll())
        self.assertFalse(worker.disabled)
        self.assertTrue(worker.process.is_alive())
        self.assertTrue(worker.submit(scene))

    def test_menu_owned_pause_retry_and_return_work_in_every_mode(self):
        for enabled, strategy, random_map in ((False, 'simple', False),
                (True, 'simple', False), (True, 'hard', False),
                (True, 'simple', True), (True, 'hard', True)):
            with self.subTest(enabled=enabled, strategy=strategy, random=random_map):
                w, clock, app = self.make_app(menu=True,
                    scheduler_factory=lambda strategy=strategy: AgentScheduler(InlineWorker(make_policy(strategy))))
                app.ui.selection.bot_enabled = enabled
                app.ui.selection.strategy = strategy
                app.ui.selection.random_map = random_map
                self.frame(w, clock, app, ('enter',))
                self.frame(w, clock, app, dt=.13)
                self.frame(w, clock, app)
                self.frame(w, clock, app, ('esc',), ('esc',))
                self.frame(w, clock, app)
                self.assertEqual('next_map' in app.ui.rows(), random_map)
                old_scheduler, before = app.scheduler, app.scene
                self.frame(w, clock, app, dt=10)
                self.assertEqual(app.scene, before)
                app.ui.focus = 'retry'
                self.frame(w, clock, app, ('enter',), ('enter',))
                self.frame(w, clock, app)
                self.assertEqual(app.scene['round_id'], 2)
                self.assertEqual(app.scene['observation_tick'], 0)
                if enabled:
                    self.assertIsNot(app.scheduler, old_scheduler)
                self.frame(w, clock, app, ('esc',), ('esc',))
                self.frame(w, clock, app)
                app.ui.focus = 'menu'
                self.frame(w, clock, app, ('enter',), ('enter',))
                self.frame(w, clock, app)
                self.assertIsNone(app.world)
                self.assertIsNone(app.scheduler)
                self.assertEqual(app.ui.screen, 'menu')
