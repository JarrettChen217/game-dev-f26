"""Four opponents, one authoritative game; no model learning or physics substitute."""
import unittest
from unittest.mock import patch

from tank_game.agents import AgentScheduler, InlineWorker
from tank_game.controllers import keyboard_request
from tank_game.session import GameSession
from tank_game.strategies import make_policy
from tank_game.ui import MenuSelection


class Policy:
    calls = 0
    def action(self, features, mask):
        self.calls += 1
        return 14


def scheduler(strategy):
    return AgentScheduler(InlineWorker(make_policy(strategy)))


class UnifiedGameTests(unittest.TestCase):
    def session(self, strategy, random_map=False):
        with patch('tank_game.laika_60hz.mac_play.ReleasedPolicy', return_value=Policy()):
            session = GameSession(MenuSelection(True, strategy, random_map), seed=1000,
                                  scheduler_factory=lambda strategy=strategy: scheduler(strategy))
        self.addCleanup(session.close)
        return session

    def test_all_four_share_initial_map_physics_render_and_seat_labels(self):
        first = None
        for name in ('simple', 'hard', 'laika', 'hybrid'):
            with self.subTest(name=name):
                session = self.session(name)
                scene = session.world.observe('tank-1')
                self.assertEqual(scene.get('rules_profile'), 'laika-source-60hz-v1')
                common = scene['map'], scene['rules'], scene['all_tanks'], session.world.raw_render
                if first is None: first = common
                self.assertEqual(common, first)
                self.assertEqual(session.world.presentation_seats[0], ('tank-1', 'YOU'))
                self.assertEqual(scene['controller_roles']['tank-2'],
                                 {'hybrid':'hybrid-u19588', 'laika':'source-laika-60hz'}.get(name, name))
                self.assertEqual(scene['rules']['tick_rate'], 60)
                self.assertEqual(scene['rules']['settlement_frames'], 180)
                if name in ('laika','hybrid'):
                    self.assertIsNone(session.scheduler)
                else:
                    self.assertIsNotNone(session.scheduler)

    def test_scripted_opponents_really_decide_without_hidden_native_ai(self):
        for name in ('simple','hard'):
            with self.subTest(name=name):
                session = self.session(name)
                before = session.world.observe('tank-2')['all_tanks']
                for _ in range(90): session.runner.tick()
                self.assertGreater(session.scheduler.decisions, 0)
                self.assertEqual(session.scheduler.failures, 0)
                self.assertEqual(session.world.diagnostics['laika_calls'], 0)
                self.assertEqual(session.world.diagnostics['model_calls'], 0)
                self.assertNotEqual(session.world.observe('tank-2')['all_tanks'], before)
                self.assertEqual(session.world.rejected_actions, 0)

    def test_native_laika_and_exact_policy_have_distinct_execution(self):
        for name in ('laika','hybrid'):
            session = self.session(name)
            for _ in range(20): session.runner.tick()
            diag = session.world.diagnostics
            self.assertEqual(diag['world_steps'], 20)
            self.assertEqual(diag['model_calls'], 20 if name == 'hybrid' else 0)
            self.assertEqual(diag['laika_calls'] > 0, name == 'laika')

    def test_retry_retains_score_new_session_clears_and_fixed_map_blocks_next(self):
        for name in ('simple','hard','laika','hybrid'):
            session = self.session(name)
            score = session.random_session.score
            from tank_game.match_hud import MatchFacts
            score.record(MatchFacts(1, 'finished', ('tank-1',), winner_id='tank-1'))
            before = score.points.copy()
            session.runner.tick()
            self.assertTrue(session.transition('retry', allow_active=True))
            self.assertEqual(session.world.observe('tank-1')['observation_tick'], 0)
            self.assertEqual(score.points, before)
            self.assertFalse(session.transition('next_map', allow_active=True))
            session.close()
            self.assertTrue(all(v == 0 for v in score.points.values()))
            self.assertIsNone(session.world._bridge.handle)

    def test_external_opponent_action_ingress_is_identity_bound(self):
        session = self.session('simple'); w = session.world
        scene = w.observe('tank-2')
        data = keyboard_request(scene, {'forward'})
        w.submit_action('tank-2', data)
        w.submit_action('tank-2', data)  # one request per tank per tick
        self.assertEqual(w.rejected_actions, 1)
        w.step()
        self.assertEqual(w.diagnostics['last_opponent_action'], 14)
        w.step()
        self.assertEqual(w.diagnostics['last_opponent_action'], 8)


class EntryAndLifecycleTests(unittest.TestCase):
    def test_normal_duel_cli_uses_unified_session_for_each_opponent(self):
        from tank_game.__main__ import main
        for strategy in ('simple','hard','laika','hybrid'):
            with (self.subTest(strategy=strategy),
                  patch('sys.argv',['tank_game','--duel','--strategy',strategy]),
                  patch('tank_game.session.GameSession') as factory,
                  patch('tank_game.app.main') as launch):
                main()
                self.assertEqual(factory.call_count,1)
                self.assertIs(launch.call_args.kwargs['game_session'], factory.return_value)

    def test_every_menu_opponent_uses_shared_render_and_pause_is_frozen(self):
        from tank_game.app import DrivingApp
        from tank_game.window_state import NativeWindowObserver, RawWindow
        from tests.test_original_laika_app import OriginalWindow
        from tests.test_realtime import Clock
        for strategy in ('simple','hard','laika','hybrid'):
            with self.subTest(strategy=strategy):
                window,clock=OriginalWindow(),Clock()
                with patch('tank_game.laika_60hz.mac_play.ReleasedPolicy',return_value=Policy()):
                    app=DrivingApp(window,menu=True,clock=clock,
                        scheduler_factory=lambda strategy=strategy: scheduler(strategy),
                        window_observer=NativeWindowObserver(reader=lambda:RawWindow(True,(920,464),(100,100),(1,))))
                    self.addCleanup(app.close)
                    app.ui.selection.strategy=strategy;app.ui.selection.random_map=False;app.ui.focus='start'
                    window.pressed,window.held={'enter'},{'enter'};clock.now+=.01;app.update()
                    window.pressed,window.held=set(),set();clock.now+=.2;app.update()
                    self.assertTrue(app._source60_engine)
                    self.assertTrue(app._original_engine)
                    self.assertFalse(app.ui.original_rules)
                    app.ui.screen,app.ui.focus='pause','resume'
                    snapshot=app.world.raw_render;diag=app.world.diagnostics
                    for _ in range(5): clock.now+=1;app.update();app.draw()
                    self.assertEqual(app.world.raw_render,snapshot)
                    self.assertEqual(app.world.diagnostics,diag)
                    with patch.object(app, '_menu_operation', return_value='menu'):
                        app._results_update(clock.now)
                    self.assertEqual(app.ui.screen,'menu')
                    self.assertIsNone(app.world)
