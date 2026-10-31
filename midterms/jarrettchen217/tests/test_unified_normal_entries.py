"""All normal factories use native source60 rules; no legacy World substitution."""
import unittest
from unittest.mock import patch

from tank_game.controllers import keyboard_request
from tank_game.session import GameSession
from tank_game.ui import MenuSelection


class NativeEntryTests(unittest.TestCase):
    def test_practice_factory_has_one_native_human_and_no_duel_score(self):
        with patch('tank_game.world.World', side_effect=AssertionError('legacy world')):
            session=GameSession(MenuSelection(bot_enabled=False,strategy='hybrid'))
        self.addCleanup(session.close)
        s=session.world.observe('tank-1')
        self.assertEqual(s.get('rules_profile'),'laika-source-60hz-v1')
        self.assertNotIn('duel',s)
        self.assertEqual(len(s['tanks']),1)
        self.assertIsNone(session.random_session.score)
        self.assertIsNone(session.scheduler)
        self.assertEqual(session.world.diagnostics['native_ai_seats'],[False,False])

    def test_five_lessons_use_native_factories_and_release_gate(self):
        from tank_game.tutorial import make_tutorial_scenario
        for lesson in range(1,6):
            with self.subTest(lesson=lesson):
                scenario=make_tutorial_scenario(lesson);self.addCleanup(scenario.world.close)
                w=scenario.world;s=w.observe('tank-1')
                self.assertEqual(s.get('rules_profile'),'laika-source-60hz-v1')
                self.assertEqual(s['rules']['tick_rate'],60)
                self.assertEqual(s['rules']['fire_interval'],0)
                self.assertEqual(s['rules']['bullet_lifetime'],10)
                self.assertEqual(w.native_facts['shots_fired'],0)
                self.assertIsNone(w._bridge.features)
                self.assertIsNone(w._bridge.mask)
                self.assertTrue(s['self_status']['trigger_released'])
                self.assertEqual(w.diagnostics['native_ai_seats'],[False,False])

    def test_native_ammo_requires_release_then_repress(self):
        from tank_game.tutorial import make_tutorial_scenario
        w=make_tutorial_scenario(5).world;self.addCleanup(w.close)
        def tick(fire):
            w.submit_action('tank-1',keyboard_request(w.observe('tank-1'),set(),fire_pressed=fire));w.step()
        for _ in range(4):tick(True)
        self.assertEqual(w.native_facts['shots_fired'],1)
        tick(False);tick(True)
        self.assertEqual(w.native_facts['shots_fired'],2)

    def test_all_five_lessons_finish_through_real_native_actions(self):
        from math import atan2, degrees, hypot

        from tank_game.tutorial import TutorialSession
        session=TutorialSession();self.addCleanup(session.close)
        for lesson in range(1,6):
            w=session.scenario.world
            if lesson<=2:
                size=w.observe('tank-1')['map']['tile_size']
                waypoints=([(5*size,1.5*size),(5*size,.9*size)] if lesson==1 else
                           [(7*size,5*size),(7*size,size)])
                for x,y in waypoints:
                    for _ in range(400):
                        scene=w.observe('tank-1');t=scene['tanks'][0]
                        if hypot(x-t['x'],y-t['y'])<.08*size:break
                        error=(degrees(atan2(y-t['y'],x-t['x']))-t['heading_deg']+180)%360-180
                        held={'turn_right' if error>0 else 'turn_left'} if abs(error)>2.1 else {'forward'}
                        session.tick(keyboard_request(scene,held))
                        if session.phase!='active':break
                for _ in range(15):session.tick(keyboard_request(w.observe('tank-1'),set()))
            else:
                for i in range(850):
                    session.tick(keyboard_request(w.observe('tank-1'),set(),fire_pressed=i==0))
                    if session.phase!='active':break
            self.assertEqual(session.phase,'complete' if lesson==5 else 'success',(lesson,session.error))
            if lesson<5:
                old=w;self.assertTrue(session.advance());self.assertIsNone(old._bridge.handle)
        self.assertEqual(session.ammo_shots_fired,5)
        self.assertEqual(session._ammo_peak,5)
        self.assertEqual(len(session._ammo_expired),5)

    def test_practice_moves_fires_retries_and_never_allocates_model(self):
        from tank_game.actions import Action
        with patch('tank_game.laika_60hz.mac_play.ReleasedPolicy',side_effect=AssertionError('model in practice')):
            s=GameSession(MenuSelection(False,'hybrid',False))
        self.addCleanup(s.close);w=s.world;before=w.observe('tank-1')['tanks'][0]
        for _ in range(20):s.controllers['tank-1'].set_input(Action(0,1));s.runner.tick()
        self.assertNotEqual(w.observe('tank-1')['tanks'][0]['heading_deg'],before['heading_deg'])
        s.controllers['tank-1'].set_input(Action(fire=True));s.runner.tick()
        self.assertEqual(w.native_facts['shots_fired'],1)
        self.assertTrue(s.transition('retry',allow_active=True))
        self.assertEqual(w.native_facts['shots_fired'],0)
        self.assertIsNone(s.random_session.score)
        self.assertFalse(s.transition('next_map',allow_active=True))

    def test_tutorial_close_cannot_reopen_native_resources(self):
        from tank_game.tutorial import TutorialSession
        s=TutorialSession();s.close();s.close()
        self.assertIsNone(s.scenario.world._bridge.handle)
        self.assertFalse(s.retry())

    def test_practice_tutorial_and_duel_switches_close_old_worlds_and_isolate_scores(self):
        from tank_game.agents import AgentScheduler, InlineWorker
        from tank_game.strategies import make_policy
        from tests.test_tutorial_app import TutorialAppTests
        w,clock,app=TutorialAppTests.make_app(self,scheduler_factory=lambda:AgentScheduler(InlineWorker(make_policy('simple'))))
        def frame(pressed=(),held=(),dt=1/60):
            TutorialAppTests.frame(self,w,clock,app,pressed,held,dt)
        def start():
            app.ui.focus='start';frame(('enter',),('enter',));frame(dt=.2);frame()
        app.ui.selection.bot_enabled=False;start();practice=app.world
        self.assertTrue(app._source60_engine);self.assertIsNone(app.match_score)
        app.ui.screen='pause'
        with patch.object(app,'_menu_operation',return_value='menu'):app._results_update(clock.now)
        self.assertIsNone(practice._bridge.handle)
        self.assertTrue(app._start_tutorial());lesson=app.world;app._skip_tutorial()
        self.assertIsNone(lesson._bridge.handle)
        self.assertFalse(app.tutorial_progress_path.exists())
        frame();app.ui.selection.bot_enabled=True;app.ui.selection.random_map=False;start()
        self.assertEqual(app.match_score.points,{'tank-1':0,'tank-2':0})
        self.assertIsNotNone(app.world._bridge.handle)
