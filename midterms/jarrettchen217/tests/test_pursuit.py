"""Pursuit uses public geometry and bounded ordinary-action steering."""

import unittest
from copy import deepcopy
from dataclasses import replace

from tank_game.agents import AgentScheduler, InlineWorker
from tank_game.controllers import keyboard_request
from tank_game.map import Spawn, WallEdge
from tank_game.pursuit import PursuitPolicy
from tank_game.world import World
from tests.test_driving import open_map
from tests.test_duel import duel


class Pulse:
    def __init__(self, ticks):
        self.ticks = ticks

    def decide(self, scene):
        return dict(keyboard_request(scene, {'d'}), turn_ticks=self.ticks)


class DelayedPulse:
    def __init__(self, original):
        self.result = original, Pulse(2).decide(original), .01

    def submit(self, scene):
        return False

    def poll(self):
        result, self.result = self.result, None
        return result


class PursuitTests(unittest.TestCase):

    def test_delayed_hard_aiming_eventually_fires(self):
        from tank_game.prediction import HardPolicy

        class DelayedWorker:
            def __init__(self, delays):
                self.policy=HardPolicy()
                self.delays=iter(delays*40)
                self.current_tick=0
                self.pending=None

            def submit(self, scene):
                if self.pending is not None:
                    return False
                original=deepcopy(scene)
                self.pending=(scene['observation_tick']+next(self.delays),
                              (original,self.policy.decide(original),.01))
                return True

            def poll(self):
                if self.pending is not None and self.current_tick>=self.pending[0]:
                    result=self.pending[1]
                    self.pending=None
                    return result
                return None

            def close(self):
                pass

        for delays in ([1],[1,3,5,2]):
            with self.subTest(delays=delays):
                world=duel(a=Spawn(80,80,0),b=Spawn(230,89,180))
                worker=DelayedWorker(delays)
                scheduler=AgentScheduler(worker)
                fired=False
                for _ in range(180):
                    scene=world.observe('tank-1')
                    worker.current_tick=scene['observation_tick']
                    request=scheduler.request(scene)
                    fired |= request['fire']
                    world.submit_action('tank-1',request)
                    world.step()
                    if fired:
                        break
                self.assertTrue(fired)
                self.assertEqual(world.rejected_actions,0)
                self.assertEqual(scheduler.rejected,0)

    def test_shared_pulse_turns_three_degrees_then_stops(self):
        w = World(open_map(Spawn(112, 112, 0)))
        scheduler = AgentScheduler(InlineWorker(Pulse(1)))
        turns = []
        for _ in range(6):
            request = scheduler.request(w.observe('tank-1'))
            self.assertNotIn('turn_ticks', request)
            turns.append(request['turn'])
            w.submit_action('tank-1', request)
            w.step()
        self.assertEqual(turns, [1, 0, 0, 0, 0, 0])
        self.assertEqual(w.observe('tank-1')['tanks'][0]['heading_deg'], 3)
        self.assertEqual(w.rejected_actions, 0)

    def test_target_heading_validation_and_original_expiry(self):
        class TargetPolicy:
            def __init__(self, target):
                self.target=target
            def decide(self, scene):
                return dict(keyboard_request(scene,{'d'}),turn_ticks=6,
                            turn_target_deg=self.target)

        for target in (True,'3',float('inf'),float('nan'),-1,360):
            scheduler=AgentScheduler(InlineWorker(TargetPolicy(target)))
            self.assertEqual(scheduler.request(World().observe('tank-1'))['turn'],0)
            self.assertEqual(scheduler.rejected,1)
        world=World(open_map(Spawn(112,112,0)))
        scheduler=AgentScheduler(InlineWorker(TargetPolicy(3.4)))
        turns=[]
        for _ in range(6):
            action=scheduler.request(world.observe('tank-1'))
            self.assertNotIn('turn_target_deg',action)
            turns.append(action['turn'])
            world.submit_action('tank-1',action)
            world.step()
        self.assertEqual(turns,[1,0,0,0,0,0])
        # A long target pulse that arrives at tick5 has only that tick left.
        scene=World().observe('tank-1')
        worker=DelayedPulse(scene)
        worker.result=(scene,dict(keyboard_request(scene,{'d'}),
                                 turn_ticks=6,turn_target_deg=90),.01)
        scheduler=AgentScheduler(worker)
        self.assertEqual(scheduler.request(dict(scene,observation_tick=5))['turn'],1)
        self.assertEqual(scheduler.request(dict(scene,observation_tick=6))['turn'],0)

    def test_invalid_pulses_idle_and_count_rejection(self):
        for ticks in (-1, 7, True, 1.5, '1'):
            scheduler = AgentScheduler(InlineWorker(Pulse(ticks)))
            request = scheduler.request(World().observe('tank-1'))
            self.assertEqual(request['turn'], 0)
            self.assertEqual(scheduler.rejected, 1)

    def test_delayed_pulse_does_not_restart_its_duration(self):
        scene = World().observe('tank-1')
        scheduler = AgentScheduler(DelayedPulse(scene))
        scene = dict(scene, observation_tick=3)
        self.assertEqual(scheduler.request(scene)['turn'], 0)
        self.assertEqual(scheduler.rejected, 0)

    def test_aims_at_non_eighteen_degree_heading_and_fires_actual_projectile(self):
        w = duel(a=Spawn(112, 112, 0), b=Spawn(176, 130, 180))
        scheduler = AgentScheduler(InlineWorker(PursuitPolicy()))
        fired = False
        for _ in range(60):
            request = scheduler.request(w.observe('tank-1'))
            fired |= request['fire']
            w.submit_action('tank-1', request)
            w.step()
            if w.observe('tank-1')['bullets']:
                break
        self.assertTrue(fired)
        self.assertTrue(w.observe('tank-1')['bullets'])
        self.assertEqual(w.rejected_actions, 0)

    def test_wall_separated_opponent_has_a_nonoverlapping_reachable_goal(self):
        m = open_map(Spawn(112, 112, 0))
        m = replace(m, edges=m.edges+(WallEdge('vertical', 4, 3),))
        w = World(m, duel=True, spawns=(m.spawn, Spawn(144, 112, 180)))
        policy = PursuitPolicy()
        scene = w.observe('tank-1')
        before = deepcopy(scene)
        policy.decide(scene)
        self.assertIsNotNone(policy.goal)
        self.assertNotEqual(policy.navigator.nodes[policy.goal], (144, 112))
        self.assertTrue(policy.navigator.waypoints)
        self.assertEqual(scene, before)

    def test_no_other_tank_falls_back_to_repeatable_patrol(self):
        scene = World().observe('tank-1')
        a, b = PursuitPolicy(), PursuitPolicy()
        for tick in range(0, 48, 6):
            scene['observation_tick'] = tick
            self.assertEqual(a.decide(scene), b.decide(scene))
        self.assertIsNone(a.goal)

    def test_new_round_rebuilds_pursuit_state(self):
        scene = duel().observe('tank-1')
        policy = PursuitPolicy()
        policy.decide(scene)
        old = policy.navigator
        scene['round_id'] = 2
        policy.decide(scene)
        self.assertIsNot(policy.navigator, old)

    def test_actual_wall_detour_eventually_creates_a_projectile(self):
        m = open_map(Spawn(112, 112, 0))
        m = replace(m, edges=m.edges+(WallEdge('vertical', 4, 3),))
        w = World(m, duel=True, spawns=(m.spawn, Spawn(144,112,180)))
        scheduler = AgentScheduler(InlineWorker(PursuitPolicy()))
        ys = []
        for _ in range(900):
            w.submit_action('tank-1', scheduler.request(w.observe('tank-1')))
            w.step()
            ys.append(w._tanks['tank-1'].y)
            if w.observe('tank-1')['bullets']:
                break
        self.assertTrue(w.observe('tank-1')['bullets'])
        self.assertTrue(min(ys) < 96 or max(ys) > 128)
        self.assertEqual(w.rejected_actions, 0)

    def test_moving_opponent_replans_before_periodic_deadline(self):
        m = open_map(Spawn(112,112,0))
        m = replace(m, edges=m.edges+(WallEdge('vertical',4,3),))
        scene = World(m,duel=True,spawns=(m.spawn,Spawn(144,112,180))).observe('tank-1')
        policy = PursuitPolicy()
        policy.decide(scene)
        scene['observation_tick'] = 6
        scene['tanks'][1]['x'] = 208
        policy.decide(scene)
        self.assertEqual(policy.opponent_point, (208,112))
        self.assertEqual(policy.last_plan, 6)

    def test_disconnected_public_geometry_falls_back_without_targeting_other_tank(self):
        scene = duel(a=Spawn(112,112,0),b=Spawn(144,112,180)).observe('tank-1')
        scene['map']['walls'].append({'x':127,'y':0,'width':2,
                                     'height':scene['map']['height']})
        policy = PursuitPolicy()
        from tank_game.patrol import SimplePatrol
        self.assertEqual(policy.decide(scene), SimplePatrol().decide(scene))
        self.assertIsNone(policy.goal)
