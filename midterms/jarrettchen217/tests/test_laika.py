"""Reference Laika behaviors through detached observations and the real Tank rules."""
import unittest
from copy import deepcopy

from tank_game.agents import AgentScheduler, InlineWorker
from tank_game.map import Spawn
from tank_game.strategies import POLICIES, make_policy
from tests.test_duel import duel


class LaikaTests(unittest.TestCase):
    def policy(self):
        self.assertIn('laika', POLICIES, 'native Laika is missing')
        return make_policy('laika')

    def test_direct_aim_fires_through_legal_native_actions(self):
        world = duel(a=Spawn(112,112,0), b=Spawn(176,112,180))
        policy = self.policy()
        scheduler = AgentScheduler(InlineWorker(policy), decision_hz=20)
        fired = False
        for _ in range(120):
            scene = world.observe('tank-1')
            req = scheduler.request(scene)
            fired |= req['fire']
            world.submit_action('tank-1', req)
            world.step()
            if world.observe('tank-1')['round_status'] != 'PLAYING':
                break
        self.assertTrue(fired)
        self.assertEqual(world.observe('tank-1')['duel']['result'], 'tank-1')
        self.assertEqual(world.rejected_actions, 0)

    def test_detached_input_is_unchanged_and_new_policies_are_deterministic(self):
        first, second = self.policy(), self.policy()
        world = duel(a=Spawn(48,48,90), b=Spawn(208,208,180))
        for _ in range(30):
            scene = world.observe('tank-1')
            before = deepcopy(scene)
            a, b = first.decide(scene), second.decide(scene)
            self.assertEqual(a, b)
            self.assertEqual(scene, before)
            world.submit_action('tank-1', a)
            world.step()

    def test_new_round_discards_the_previous_action_stack(self):
        policy = self.policy()
        world = duel(a=Spawn(112,112,90), b=Spawn(176,112,180))
        policy.decide(world.observe('tank-1'))
        scene = world.observe('tank-1')
        scene['round_id'] += 1
        self.assertEqual(policy.decide(scene), self.policy().decide(scene))

    def test_terminal_state_stops_all_axes_and_fire(self):
        policy = self.policy()
        scene = duel().observe('tank-1')
        policy.decide(scene)
        scene['round_status'] = 'DYING'
        request = policy.decide(scene)
        self.assertEqual((request['throttle'], request['turn'], request['fire']), (0,0,False))

    def test_explicit_public_own_contact_takes_priority_over_motion_inference(self):
        policy = self.policy()
        scene = duel(a=Spawn(112,112,0),b=Spawn(176,112,180)).observe('tank-1')
        policy.decide(scene)
        scene['observation_tick'] = 36
        policy.decide(scene)
        scene['observation_tick'] = 39
        # Optional self-only event from a host/profile, never opponent internals.
        scene['self_status']['wall_contact'] = True
        policy.decide(scene)
        self.assertEqual(policy.goal.kind,'back')

    def test_real_world_pursuit_detours_a_wall_before_firing(self):
        from dataclasses import replace

        from tank_game.map import WallEdge
        from tank_game.world import World
        from tests.test_driving import open_map
        maze = open_map(Spawn(48,48,90))
        maze = replace(maze,edges=maze.edges+tuple(WallEdge('vertical',2,y) for y in range(6)))
        world = World(maze,duel=True,spawns=(maze.spawn,Spawn(272,48,180)))
        policy = self.policy()
        schedule = AgentScheduler(InlineWorker(policy),decision_hz=20)
        crossed_gap = False
        for _ in range(1100):
            scene = world.observe('tank-1')
            tank = next(t for t in scene['tanks'] if t['id']=='tank-1')
            crossed_gap |= tank['x']>65 and tank['y']>192
            world.submit_action('tank-1',schedule.request(scene))
            world.step()
            if world.observe('tank-1')['round_status']!='PLAYING':
                break
        self.assertTrue(crossed_gap,'tank did not traverse the open end of the barrier')
        self.assertEqual(world.observe('tank-1')['duel']['result'],'tank-1')
        self.assertEqual((world.rejected_actions,schedule.failures,schedule.rejected),(0,0,0))

    def test_native_ricochet_aim_hits_a_target_behind_a_wall(self):
        from dataclasses import replace
        from math import atan2, degrees

        from tank_game.map import WallEdge
        from tank_game.world import World
        from tests.test_driving import open_map
        heading = degrees(atan2(-153,96))%360
        maze = open_map(Spawn(80,80,heading))
        maze = replace(maze,edges=maze.edges+(WallEdge('vertical',4,2),))
        world = World(maze,duel=True,spawns=(maze.spawn,Spawn(176,80,180)))
        policy = self.policy()
        schedule = AgentScheduler(InlineWorker(policy),decision_hz=20)
        for _ in range(300):
            scene = world.observe('tank-1')
            world.submit_action('tank-1',schedule.request(scene))
            world.step()
            if world.observe('tank-1')['round_status']!='PLAYING':
                break
        self.assertEqual(world.observe('tank-1')['duel']['result'],'tank-1')
        self.assertEqual(world.rejected_actions,0)

    def test_dodge_uses_anonymous_projectiles_including_our_own(self):
        from tank_game.entities import BulletState
        outcomes = []
        for owner in ('tank-1','tank-2'):
            world = duel(a=Spawn(112,112,0),b=Spawn(272,272,180))
            policy = self.policy()
            schedule = AgentScheduler(InlineWorker(policy),decision_hz=20)
            dodged = False
            for tick in range(240):
                if tick==60:
                    world._bullets=(BulletState('fixture',112,30,0,90,radius=1.5,owner_id=owner),)
                scene = world.observe('tank-1')
                # Harness disables firing to isolate movement/dodge behavior.
                scene['self_status']['can_fire'] = False
                world.submit_action('tank-1',schedule.request(scene))
                dodged |= policy.goal.kind=='dodge'
                world.step()
                if world.observe('tank-1')['round_status']!='PLAYING':
                    break
            self.assertTrue(dodged)
            self.assertTrue(world.observe('tank-1')['self_status']['alive'])
            outcomes.append(world.observe('tank-1')['tanks'][0]['x'])
        self.assertGreater(min(outcomes),128)

    def test_action_stack_and_timers_persist_between_requests(self):
        policy = self.policy()
        world = duel(a=Spawn(112,112,90),b=Spawn(176,112,180))
        scene = world.observe('tank-1')
        policy.decide(scene)
        scene['observation_tick'] = 36
        policy.decide(scene)
        scene['observation_tick'] = 39
        policy.decide(scene)
        stack = policy.actions
        first_goal = policy.goal
        scene['observation_tick'] = 42
        policy.decide(scene)
        self.assertIs(policy.actions,stack)
        self.assertIs(policy.goal,first_goal)
        self.assertGreater(len(stack),0)
        self.assertAlmostEqual(first_goal.period,.35)
        before = (first_goal.period,len(stack))
        request = policy.decide(scene)
        self.assertEqual((first_goal.period,len(stack)),before)
        self.assertFalse(request['fire'])

    def test_a_held_fire_stack_entry_does_not_repeat_after_native_cooldown(self):
        from tank_game.laika import Goal, StackAction
        world = duel(a=Spawn(48,48,0),b=Spawn(272,272,180))
        policy = self.policy()
        policy.decide(world.observe('tank-1'))
        policy.goal = Goal('idle',period=10,continuous=False)
        policy.actions = [StackAction('fire',remaining=1)]
        schedule = AgentScheduler(InlineWorker(policy),decision_hz=20)
        for _ in range(48):
            scene = world.observe('tank-1')
            world.submit_action('tank-1',schedule.request(scene))
            world.step()
        self.assertEqual(world.observe('tank-1')['self_status']['active_bullets'],1)
