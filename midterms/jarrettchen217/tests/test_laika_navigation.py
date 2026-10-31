"""Native rectangle steering must execute Laika's route without a wall loop."""
import unittest
from dataclasses import replace

from tank_game.agents import AgentScheduler, InlineWorker
from tank_game.laika import Goal, LaikaPolicy, StackAction
from tank_game.map import GameMap, Spawn, WallEdge
from tank_game.world import World


def barrier_world(profile='rectangle', turns=0):
    edges = tuple([WallEdge('horizontal', x, y) for y in (0, 10) for x in range(10)]
                  + [WallEdge('vertical', x, y) for x in (0, 10) for y in range(10)]
                  + [WallEdge('vertical', 2, y) for y in range(6)])
    own, target = Spawn(48, 48, 90), Spawn(272, 48, 180)
    for _ in range(turns):
        edges = tuple(WallEdge('vertical', 10-e.row, e.column) if e.orientation == 'horizontal'
                      else WallEdge('horizontal', 9-e.row, e.column) for e in edges)
        own = Spawn(320-own.y, own.x, (own.heading_deg+90) % 360)
        target = Spawn(320-target.y, target.x, (target.heading_deg+90) % 360)
    maze = GameMap(10, 10, edges, spawn=own)
    return World(maze, duel=True, spawns=(own, target),
                 collision_profile=profile)


class LaikaNavigationTests(unittest.TestCase):
    def test_delayed_realtime_decisions_do_not_restart_the_same_cell_forever(self):
        class DelayedWorker(InlineWorker):
            """Real policy execution with deterministic one/two-tick delivery."""
            tick = 0

            def submit(self, scene):
                if self.result is not None:
                    return False
                accepted = super().submit(scene)
                self.ready = scene['observation_tick']+self.delay
                return accepted

            def poll(self):
                return super().poll() if self.result is not None and self.tick >= self.ready else None

        for delay in (1, 2):
            with self.subTest(delivery_delay_ticks=delay):
                world = barrier_world()
                worker = DelayedWorker(LaikaPolicy())
                worker.delay = delay
                scheduler = AgentScheduler(worker, decision_hz=20)
                crossed_gap = False
                try:
                    for tick in range(2200):
                        worker.tick = tick
                        scene = world.observe('tank-1')
                        tank = scene['tanks'][0]
                        if tank['x'] > 65 and tank['y'] > 192:
                            crossed_gap = True
                            break
                        scene['self_status']['can_fire'] = False
                        world.submit_action('tank-1', scheduler.request(scene))
                        world.step()
                    self.assertTrue(crossed_gap, 'delayed inputs looped around the current cell')
                    self.assertEqual((scheduler.failures, scheduler.rejected, world.rejected_actions),
                                     (0, 0, 0))
                finally:
                    scheduler.close()

    def test_existing_wall_scrape_can_back_out_and_resume_the_route(self):
        world = barrier_world()
        # Valid rectangle pose already too close for a full rotation, as can
        # happen after a dodge. Only the fixture places it; policy sees public data.
        world._tanks['tank-1'] = replace(world._tanks['tank-1'], x=55.125, y=91,
                                       heading_deg=24)
        policy = LaikaPolicy()
        scheduler = AgentScheduler(InlineWorker(policy), decision_hz=20)
        self.addCleanup(scheduler.close)
        crossed_gap = False
        for _ in range(1500):
            scene = world.observe('tank-1')
            tank = scene['tanks'][0]
            if tank['x'] > 65 and tank['y'] > 192:
                crossed_gap = True
                break
            scene['self_status']['can_fire'] = False
            world.submit_action('tank-1', scheduler.request(scene))
            world.step()
        self.assertTrue(crossed_gap, 'clearance guard trapped the existing wall recovery')

    def test_rectangle_traverses_the_barrier_in_all_four_orientations(self):
        for turns in range(4):
            with self.subTest(quarter_turns=turns):
                world = barrier_world(turns=turns)
                policy = LaikaPolicy()
                scheduler = AgentScheduler(InlineWorker(policy), decision_hz=20)
                crossed_gap = False
                try:
                    for _ in range(1500):
                        scene = world.observe('tank-1')
                        x, y = scene['tanks'][0]['x'], scene['tanks'][0]['y']
                        for _ in range(turns):
                            x, y = y, 320-x
                        if x > 65 and y > 192:
                            crossed_gap = True
                            break
                        # Isolate geometry/steering from source ricochet/dodge choices.
                        scene['self_status']['can_fire'] = False
                        world.submit_action('tank-1', scheduler.request(scene))
                        world.step()
                    self.assertTrue(crossed_gap, 'did not traverse the only opening')
                    self.assertEqual((scheduler.failures, world.rejected_actions), (0, 0))
                finally:
                    scheduler.close()

    def test_rectangle_keeps_room_to_turn_before_advancing_beside_a_wall(self):
        world = barrier_world()
        scene = world.observe('tank-1')
        policy = LaikaPolicy()
        policy.decide(scene)
        scene['tanks'][0].update(x=54.5, y=112, heading_deg=24)
        scene['observation_tick'] = 3
        policy.goal = Goal('drive', period=10, continuous=False)
        policy.actions = [StackAction('field', (1, 4))]
        request = policy.decide(scene)
        self.assertEqual((request['throttle'], request['turn']), (0, 1))

    def test_open_space_retains_reference_simultaneous_turn_and_forward(self):
        for profile in ('circle', 'rectangle'):
            with self.subTest(profile=profile):
                scene = barrier_world(profile).observe('tank-1')
                policy = LaikaPolicy()
                policy.decide(scene)
                scene['tanks'][0].update(x=48, y=112, heading_deg=24)
                scene['observation_tick'] = 3
                policy.goal = Goal('drive', period=10, continuous=False)
                policy.actions = [StackAction('field', (1, 4))]
                request = policy.decide(scene)
                self.assertEqual((request['throttle'], request['turn']), (1, 1))

    def test_rectangle_executes_the_detour_and_hits_instead_of_repeating_backup(self):
        world = barrier_world()
        policy = LaikaPolicy()
        scheduler = AgentScheduler(InlineWorker(policy), decision_hz=20)
        self.addCleanup(scheduler.close)
        crossed_gap = False
        for _ in range(1100):
            scene = world.observe('tank-1')
            tank = scene['tanks'][0]
            crossed_gap |= tank['x'] > 65 and tank['y'] > 192
            world.submit_action('tank-1', scheduler.request(scene))
            world.step()
            if world.observe('tank-1')['round_status'] != 'PLAYING':
                break
        self.assertTrue(crossed_gap, 'stuck before the only opening below the barrier')
        self.assertEqual(world.observe('tank-1')['duel']['result'], 'tank-1')
        self.assertEqual((scheduler.failures, scheduler.rejected, world.rejected_actions), (0, 0, 0))
