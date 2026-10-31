"""Map-derived navigation and opportunity fire must work beyond one layout."""

import unittest
from copy import deepcopy
from dataclasses import replace

from tank_game.agents import AgentScheduler, InlineWorker
from tank_game.map import Spawn, WallEdge
from tank_game.navigation import Navigator, bfs, map_graph, segment_clear, walls_from_scene
from tank_game.patrol import SimplePatrol
from tank_game.world import World
from tests.test_driving import open_map
from tests.test_duel import duel


class NavigationTests(unittest.TestCase):
    def test_bfs_detours_around_wall_and_rejects_unreachable(self):
        m = open_map(Spawn(112, 112, 0))
        m = replace(m, edges=m.edges+(WallEdge('vertical', 4, 3),))
        scene = World(m).observe('tank-1')
        nodes, graph = map_graph(scene['map'], 8)
        self.assertNotIn((4, 3), graph[(3, 3)])
        self.assertEqual(len(bfs(graph, (3, 3), (4, 3))), 4)
        self.assertEqual(bfs({(0, 0): (), (1, 0): ()}, (0, 0), (1, 0)), ())
        for key, neighbors in graph.items():
            for n in neighbors:
                self.assertTrue(segment_clear(nodes[key], nodes[n], 8,
                                               walls_from_scene(scene['map'])))

    def test_follow_route_reaches_goal_through_corner_with_normal_actions(self):
        m = open_map(Spawn(112, 112, 0))
        m = replace(m, edges=m.edges+(WallEdge('vertical', 4, 3),))
        w = World(m)
        nav = Navigator(w.observe('tank-1'))
        nav.set_goal(w.observe('tank-1'), (4, 3))
        request = None
        for tick in range(900):
            scene = w.observe('tank-1')
            if tick % 6 == 0:
                request = nav.request(scene)
            current = dict(request, observation_tick=scene['observation_tick'])
            w.submit_action('tank-1', current)
            w.step()
            if nav.arrived:
                break
        self.assertTrue(nav.arrived)
        t = w.observe('tank-1')['tanks'][0]
        self.assertAlmostEqual(t['x'], 144, delta=3)
        self.assertAlmostEqual(t['y'], 112, delta=3)
        self.assertEqual(w.rejected_actions, 0)

    def test_narrow_map_is_not_reported_traversable_for_oversized_body(self):
        scene = World().observe('tank-1')
        nodes, _ = map_graph(scene['map'], 32)
        self.assertNotIn((0, 0), nodes)


class PatrolTests(unittest.TestCase):
    def test_direct_shot_alignment_and_wall_blocking(self):
        w = duel()
        scene = w.observe('tank-1')
        self.assertTrue(SimplePatrol().decide(scene)['fire'])
        unaligned = deepcopy(scene)
        unaligned['tanks'][0]['heading_deg'] = 90
        self.assertFalse(SimplePatrol().decide(unaligned)['fire'])
        blocked = deepcopy(scene)
        blocked['map']['walls'].append({'x': 128, 'y': 64, 'width': 2, 'height': 96})
        self.assertFalse(SimplePatrol().decide(blocked)['fire'])
        scene['self_status']['can_fire'] = False
        self.assertFalse(SimplePatrol().decide(scene)['fire'])

    def test_policy_patrols_multiple_targets_without_fixed_coordinates(self):
        for m in (open_map(Spawn(112, 112, 0)),
                  replace(open_map(Spawn(48, 48, 0)), columns=10)):
            w = World(m)
            policy = SimplePatrol()
            schedule = AgentScheduler(InlineWorker(policy))
            positions = set()
            for _ in range(1000):
                scene = w.observe('tank-1')
                w.submit_action('tank-1', schedule.request(scene))
                w.step()
                t = w.observe('tank-1')['tanks'][0]
                positions.add((int(t['x']//32), int(t['y']//32)))
            self.assertGreater(len(positions), 3)
            self.assertGreater(policy.targets_visited, 1)
            self.assertEqual(w.rejected_actions, 0)

    def test_deterministic_and_does_not_mutate_public_input(self):
        a, b = SimplePatrol(), SimplePatrol()
        w = World()
        for _ in range(80):
            scene = w.observe('tank-1')
            before = deepcopy(scene)
            first, second = a.decide(scene), b.decide(scene)
            self.assertEqual(first, second)
            self.assertEqual(scene, before)
            w.submit_action('tank-1', first)
            w.step()

    def test_new_round_rebuilds_routes_and_clears_targets(self):
        p = SimplePatrol()
        scene = World().observe('tank-1')
        p.decide(scene)
        p.targets_visited = 22
        scene['round_id'] = 2
        p.decide(scene)
        self.assertLess(p.targets_visited, 2)

    def test_wall_behind_target_does_not_hide_a_valid_opportunity(self):
        scene = duel().observe('tank-1')
        scene['map']['walls'].append({'x': 190, 'y': 64, 'width': 2, 'height': 96})
        self.assertTrue(SimplePatrol().decide(scene)['fire'])

    def test_static_tank_blocker_triggers_bounded_backup_and_turn(self):
        w = duel(a=Spawn(112, 112, 90), b=Spawn(112, 132, 0))
        policy = SimplePatrol()
        schedule = AgentScheduler(InlineWorker(policy))
        backed_up = False
        min_x = 112
        for _ in range(400):
            scene = w.observe('tank-1')
            scene['self_status']['can_fire'] = False  # isolate navigation recovery
            req = schedule.request(scene)
            backed_up |= req['throttle'] == -1 and req['turn'] == 1
            w.submit_action('tank-1', req)
            w.step()
            min_x = min(min_x, w._tanks['tank-1'].x)
        self.assertTrue(backed_up)
        self.assertLess(min_x, 111)
        self.assertEqual(w.rejected_actions, 0)
