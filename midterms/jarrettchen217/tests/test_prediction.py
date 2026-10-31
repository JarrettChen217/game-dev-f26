"""Hand-derived public projectile trajectories and real danger comparisons."""

import unittest
from copy import deepcopy

from tank_game.agents import AgentScheduler, InlineWorker
from tank_game.entities import BulletState
from tank_game.map import Spawn
from tank_game.navigation import walls_from_scene
from tank_game.paths import position
from tank_game.prediction import HardPolicy, forecast_projectile
from tank_game.pursuit import PursuitPolicy
from tests.test_duel import duel


class PredictionTests(unittest.TestCase):
    def test_straight_trajectory_covers_one_second_without_private_age(self):
        scene = duel().observe('tank-1')
        bullet = {'id':'b','x':60,'y':112,'vx':100,'vy':0,'radius':2}
        forecast = forecast_projectile(bullet, walls_from_scene(scene['map']))
        self.assertEqual(len(forecast.paths), 60)
        x,y = position(forecast.paths[-1], 1/60)
        self.assertAlmostEqual(x,160)
        self.assertAlmostEqual(y,112)

    def test_bounce_and_corner_reflection_use_full_swept_paths(self):
        scene = duel().observe('tank-1')
        for vy,expected_y in ((0,300),(100,232)):
            bullet = {'id':'b','x':300,'y':300,'vx':100,'vy':vy,'radius':2}
            forecast = forecast_projectile(bullet,walls_from_scene(scene['map']))
            x,y = position(forecast.paths[-1],1/60)
            self.assertAlmostEqual(x,232,places=4)
            self.assertAlmostEqual(y,expected_y,places=4)

    def danger_world(self):
        w=duel(a=Spawn(112,112,0),b=Spawn(208,112,180))
        w._bullets=(BulletState('threat',112,60,0,100,radius=2,owner_id='tank-2'),)
        return w

    def test_danger_override_survives_where_stationary_pursuit_is_hit(self):
        outcomes=[]
        for policy in (PursuitPolicy(),HardPolicy()):
            w=self.danger_world()
            scheduler=AgentScheduler(InlineWorker(policy))
            for _ in range(60):
                scene=w.observe('tank-1')
                scene['self_status']['can_fire']=False
                if scene['round_status']=='PLAYING':
                    w.submit_action('tank-1',scheduler.request(scene))
                w.step()
            outcomes.append(w._tanks['tank-1'].alive)
            self.assertEqual(w.rejected_actions,0)
        self.assertEqual(outcomes,[False,True])

    def test_disappearance_restores_pursuit_and_state_resets_on_new_round(self):
        scene=self.danger_world().observe('tank-1')
        hard=HardPolicy()
        before=deepcopy(scene)
        response=hard.decide(scene)
        self.assertNotEqual(response['throttle'],0)
        self.assertFalse(response['fire'])
        self.assertEqual(scene,before)
        self.assertEqual(hard.tracked_ids,{'threat'})
        self.assertLessEqual(hard.search_stats['candidates'],9)
        self.assertLessEqual(hard.search_stats['tank_steps'],540)
        scene['bullets']=[]
        scene['observation_tick']=6
        self.assertEqual(hard.decide(scene),PursuitPolicy().decide(scene))
        self.assertEqual(hard.tracked_ids,set())
        scene['round_id']=2
        self.assertEqual(hard.decide(scene),HardPolicy().decide(scene))

    def test_quantization_margin_marks_near_grazing_path_as_a_threat(self):
        scene=self.danger_world().observe('tank-1')
        scene['bullets'][0]['x']=122.125
        hard=HardPolicy()
        hard.decide(scene)
        self.assertTrue(hard.evading)

    def test_no_safe_action_is_deterministic_and_bounded(self):
        scene=self.danger_world().observe('tank-1')
        scene['bullets'][0].update(x=112,y=112,vx=0,vy=0)
        a,b=HardPolicy(),HardPolicy()
        self.assertEqual(a.decide(scene),b.decide(scene))
        self.assertLessEqual(a.search_stats['candidates'],9)
        self.assertLessEqual(a.search_stats['tank_steps'],540)

    def test_reflected_and_corner_threats_override_pursuit_in_real_simulation(self):
        for diagonal in (False,True):
            outcomes=[]
            for policy in (PursuitPolicy(),HardPolicy()):
                w=duel(a=Spawn(208,208 if diagonal else 112,90),
                       b=Spawn(100,100 if diagonal else 112,0))
                w._bullets=(BulletState('bounce',260,260 if diagonal else 112,
                                       100,100 if diagonal else 0,
                                       radius=2,owner_id='tank-2'),)
                scheduler=AgentScheduler(InlineWorker(policy))
                for _ in range(120):
                    scene=w.observe('tank-1')
                    scene['self_status']['can_fire']=False
                    if scene['round_status']=='PLAYING':
                        w.submit_action('tank-1',scheduler.request(scene))
                    w.step()
                outcomes.append(w._tanks['tank-1'].alive)
                self.assertEqual(w.rejected_actions,0)
            self.assertEqual(outcomes,[False,True])

    def test_touching_opponent_does_not_hide_a_safe_reverse_escape(self):
        w=duel(a=Spawn(112,112,0),b=Spawn(128,112,0))
        w._bullets=(BulletState('threat',112,80,0,100,radius=2,owner_id='tank-2'),)
        scene=w.observe('tank-1')
        scene['self_status']['can_fire']=False
        request=HardPolicy().decide(scene)
        self.assertEqual(request['throttle'],-1)
