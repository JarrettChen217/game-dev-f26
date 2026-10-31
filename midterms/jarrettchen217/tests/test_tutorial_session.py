"""Native hits, release/repress, lifetime and transactional lesson ownership."""
import copy
import unittest
from unittest.mock import patch

from tank_game.controllers import keyboard_request
from tests.test_tutorial_scenarios import drive, goal_around_current, tutorial


class TutorialSessionTests(unittest.TestCase):
    def test_self_hit_settlement_does_not_submit_actions_for_dead_player(self):
        s = tutorial.TutorialSession()
        self.addCleanup(s.close)
        s.scenario.world.close()
        s.scenario = tutorial.make_tutorial_scenario(4)
        s._reset()
        for _ in range(400):
            drive(s, fire=True)
            if s.phase != 'active':
                break
        self.assertEqual(s.phase, 'success')
        self.assertEqual(s.scenario.world.rejected_actions, 0)

    def setUp(self):
        self.session=tutorial.TutorialSession();self.addCleanup(self.session.close)

    def test_goal_requires_full_containment_and_continuous_quarter_second(self):
        s=self.session;goal_around_current(s,-.125);drive(s,count=30)
        self.assertEqual(s.goal_dwell_seconds,0)
        goal_around_current(s,1);drive(s,count=14);self.assertEqual(s.phase,'active')
        self.assertAlmostEqual(s.goal_dwell_seconds,14/60)
        goal_around_current(s,-1);drive(s);self.assertEqual(s.goal_dwell_seconds,0)
        goal_around_current(s,1);drive(s,count=15);self.assertEqual(s.phase,'success')
        before=s.scenario.world.observe('tank-1');drive(s,{'forward'},20)
        self.assertEqual(before,s.scenario.world.observe('tank-1'))

    def test_dead_tank_cannot_complete_goal(self):
        s=self.session;goal_around_current(s);scene=copy.deepcopy(s.scenario.world.observe('tank-1'))
        scene['self_status']['alive']=False
        for _ in range(30):s._update_goal(scene)
        self.assertEqual(s.phase,'active');self.assertEqual(s.goal_dwell_seconds,0)

    def test_driving_steps_block_fire(self):
        s=self.session
        for step in (1,2):
            if step==2:s.phase='success';s.advance()
            drive(s,{'forward'},10,fire=True)
            self.assertEqual(s.scenario.world.observe('tank-1')['bullets'],[])
            self.assertEqual(s.scenario.world.native_facts['shots_fired'],0)

    def test_stale_and_malformed_requests_do_not_gain_validity_from_masking(self):
        s=self.session;w=s.scenario.world;before=w.observe('tank-1')['tanks']
        for changes in ({'observation_tick':-1},{'fire':'yes'}):
            request=keyboard_request(w.observe('tank-1'),{'forward'});request.update(changes);s.tick(request)
            self.assertEqual(w.observe('tank-1')['tanks'],before)

    def test_retry_failure_preserves_old_handle_and_success_closes_it(self):
        s=self.session;old=s.scenario.world
        with patch('tank_game.tutorial.make_tutorial_scenario',side_effect=ValueError('bad map')):
            self.assertFalse(s.retry())
        self.assertIs(s.scenario.world,old);self.assertIsNotNone(old._bridge.handle)
        self.assertTrue(s.retry());self.assertIsNone(old._bridge.handle)
        self.assertEqual(s.phase,'active');self.assertFalse(s.advance())


class TutorialDemoTests(unittest.TestCase):
    def session_at(self,step):
        s=tutorial.TutorialSession();s.scenario.world.close();s.scenario=tutorial.make_tutorial_scenario(step);s._reset()
        self.addCleanup(s.close);return s

    def finish_shot(self,s,limit=850):
        scenes=[]
        for _ in range(limit):
            scenes.append(s.scenario.world.observe('tank-1'))
            if s.phase!='active':break
            drive(s)
        return scenes

    def test_stationary_target_requires_native_hit_and_residual_settlement(self):
        s=self.session_at(3);drive(s,fire=True);scenes=self.finish_shot(s);w=s.scenario.world
        self.assertEqual(s.phase,'success');self.assertTrue(w.observe('tank-1')['self_status']['alive'])
        self.assertEqual([e.tank_id for e in w.hit_events],['tank-2'])
        self.assertTrue(any(x['effects'] for x in scenes));self.assertEqual(scenes[-1]['effects'],[])
        hit=w.hit_events[0];self.assertFalse(hit.has_bounced)
        self.assertEqual(w.observe('tank-1')['observation_tick']-round(hit.elapsed*60),180)

    def test_tutorial_score_waits_for_native_settlement_and_retry_clears_it(self):
        s=self.session_at(3);drive(s,fire=True)
        while not s.scenario.world.hit_events:drive(s)
        self.assertEqual(s.round_facts.phase,'settling')
        self.assertEqual(s.round_facts.remaining_seconds,3)
        self.assertEqual(s.round_score.points,{'tank-1':0,'tank-2':0})
        drive(s,count=90)
        self.assertEqual(s.round_facts.remaining_seconds,1.5)
        self.finish_shot(s)
        self.assertEqual(s.round_facts.winner_id,'tank-1')
        self.assertEqual(s.round_score.points,{'tank-1':1,'tank-2':0})
        drive(s,count=50)
        self.assertEqual(s.round_score.points['tank-1'],1)
        self.assertTrue(s.retry())
        self.assertEqual(s.round_facts.phase,'playing')
        self.assertEqual(s.round_score.points,{'tank-1':0,'tank-2':0})
        drive(s,fire=True);self.finish_shot(s);self.assertTrue(s.advance())
        self.assertEqual(s.round_score.points,{'tank-1':0,'tank-2':0})
        drive(s,fire=True);self.finish_shot(s)
        self.assertIsNone(s.round_facts.winner_id)
        self.assertEqual(s.round_score.points,{'tank-1':0,'tank-2':0})

    def test_self_hit_requires_native_bounce_hit_and_settlement(self):
        s=self.session_at(4);drive(s,fire=True);self.finish_shot(s);w=s.scenario.world
        self.assertEqual(s.phase,'success');self.assertTrue(s.bounce_observed)
        self.assertFalse(w.observe('tank-1')['self_status']['alive'])
        self.assertEqual([(e.tank_id,e.owner_id,e.has_bounced) for e in w.hit_events],[('tank-1','tank-1',True)])

    def test_only_one_shot_and_no_driving_during_demonstration(self):
        s=self.session_at(3);w=s.scenario.world;before=w.observe('tank-1')['tanks']
        drive(s,{'forward','turn_left'},70,fire=True)
        self.assertEqual(w.native_facts['shots_fired'],1)
        self.assertEqual(w.observe('tank-1')['tanks'][0],before[0])
        self.assertTrue(s.retry());self.assertFalse(s.shot_fired)

    def test_reading_before_fire_does_not_advance_native_clock(self):
        s=self.session_at(3);drive(s,count=8000)
        self.assertEqual(s.scenario.world.observe('tank-1')['observation_tick'],0)
        self.assertEqual(s.phase,'active')

    def test_watchdog_stops_missing_hit_without_changing_native_physics(self):
        s=self.session_at(3);drive(s,fire=True)
        # Fault is the host adapter losing time/observations; do not alter physics parameters.
        with patch.object(s.scenario.world,'step',return_value=None):self.finish_shot(s,850)
        self.assertEqual(s.phase,'error');self.assertIn('watchdog',s.error)
        self.assertTrue(s.retry());self.assertEqual(s.phase,'active')


class TutorialAmmoTests(unittest.TestCase):
    session_at = TutorialDemoTests.session_at
    def test_one_press_fills_capacity_with_release_ticks_then_native_expiry(self):
        s=self.session_at(5);transitions=[];count=0
        for tick in range(1,722):
            drive(s,fire=tick==1);scene=s.scenario.world.observe('tank-1');now=scene['self_status']['active_bullets']
            if now!=count:transitions.append((tick,now));count=now
        self.assertEqual(transitions,[(1,1),(31,2),(61,3),(91,4),(121,5),(601,4),(631,3),(661,2),(691,1),(721,0)])
        self.assertEqual(s.phase,'complete');self.assertEqual(s.ammo_shots_fired,5)
        self.assertEqual(len(s._ammo_bounced),5);self.assertEqual(len(s._ammo_expired),5)
        self.assertEqual(s.scenario.world.hit_events,())

    def test_extra_fire_does_not_restart_burst_and_movement_stays_locked(self):
        s=self.session_at(5);before=s.scenario.world.observe('tank-1')['tanks']
        drive(s,{'forward','turn_left'},800,fire=True)
        self.assertEqual(s.phase,'complete');self.assertEqual(s.scenario.world.native_facts['shots_fired'],5)
        self.assertEqual(before,s.scenario.world.observe('tank-1')['tanks'])

    def test_waiting_and_stale_fire_do_not_start_clock(self):
        s=self.session_at(5);drive(s,count=1000);w=s.scenario.world
        request=keyboard_request(w.observe('tank-1'),set(),fire_pressed=True);request['observation_tick']=-1;s.tick(request)
        self.assertFalse(s.ammo_started);self.assertEqual(w.observe('tank-1')['observation_tick'],0)

    def test_unobservable_shot_is_recoverable_error(self):
        s=self.session_at(5)
        with patch.object(s.scenario.world,'step',return_value=None):drive(s,fire=True)
        self.assertEqual(s.phase,'error');self.assertIn('not observable',s.error)
        self.assertTrue(s.retry());self.assertFalse(s.ammo_started)
