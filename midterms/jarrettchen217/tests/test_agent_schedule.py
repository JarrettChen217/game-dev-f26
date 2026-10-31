"""Real scheduler contract: original freshness, retained axes, one fire pulse."""

import multiprocessing
import time
import unittest
from copy import deepcopy

from tank_game.agents import AgentScheduler, InlineWorker, ProcessWorker
from tank_game.controllers import keyboard_request
from tank_game.world import World


class ForwardFire:
    def decide(self, scene):
        return keyboard_request(scene, {'w'}, fire_pressed=True)


class LateWorker:
    def submit(self, scene):
        self.scene = deepcopy(scene)

    def poll(self):
        if self.scene['observation_tick'] == 0:
            result = (self.scene, keyboard_request(self.scene, {'w'}, fire_pressed=True), 0)
            self.scene = dict(self.scene, observation_tick=100000)
            return result
        return None

    def close(self):
        pass


class Failing:
    def decide(self, scene):
        raise ValueError('broken policy')


class Slow:
    def __init__(self, started=None):
        self.started = started

    def decide(self, scene):
        if self.started is not None:
            self.started.value = True
        time.sleep(2)
        return keyboard_request(scene, {'w'})


class WrongSource:
    def decide(self, scene):
        result = keyboard_request(scene, {'w'})
        result['tank_id'] = 'another'
        return result


class ScheduleTests(unittest.TestCase):
    def test_retains_movement_but_not_fire_and_enters_current_tick_validation(self):
        w = World()
        schedule = AgentScheduler(InlineWorker(ForwardFire()))
        fires = []
        for _ in range(12):
            scene = w.observe('tank-1')
            req = schedule.request(scene)
            fires.append(req['fire'])
            self.assertEqual(req['observation_tick'], scene['observation_tick'])
            self.assertEqual(req['throttle'], 1)
            w.submit_action('tank-1', req)
            w.step()
        self.assertEqual(fires, [True]+[False]*5+[True]+[False]*5)
        self.assertEqual(w.rejected_actions, 0)
        self.assertEqual(schedule.decisions, 2)

    def test_delayed_decision_is_not_relabelled_fresh(self):
        scene = World().observe('tank-1')
        worker = LateWorker()
        worker.submit(scene)
        schedule = AgentScheduler(worker)
        scene['observation_tick'] = 8
        req = schedule.request(scene)
        self.assertEqual((req['throttle'], req['fire']), (0, False))
        self.assertEqual(schedule.rejected, 1)

    def test_failures_and_wrong_sources_idle(self):
        for policy in (Failing(), WrongSource()):
            schedule = AgentScheduler(InlineWorker(policy))
            req = schedule.request(World().observe('tank-1'))
            self.assertEqual((req['throttle'], req['turn'], req['fire']), (0, 0, False))
            self.assertGreater(schedule.failures+schedule.rejected, 0)

    def test_new_round_and_dead_state_clear_cached_intentions(self):
        scene = World().observe('tank-1')
        schedule = AgentScheduler(InlineWorker(ForwardFire()))
        schedule.request(scene)
        dead = dict(scene, round_status='DYING')
        self.assertEqual(schedule.request(dead)['throttle'], 0)
        new = dict(scene, round_id=2, observation_tick=1)
        self.assertEqual(schedule.request(new)['throttle'], 0)

    def test_slow_strategy_does_not_block_polling_or_accumulate_jobs(self):
        started = multiprocessing.get_context('spawn').Value('b', False)
        worker = ProcessWorker(Slow(started), timeout=2)
        try:
            scene = World().observe('tank-1')
            self.assertTrue(worker.submit(scene))
            self.assertFalse(worker.submit(scene))
            deadline = time.monotonic()+3
            while not started.value and time.monotonic() < deadline:
                time.sleep(.005)
            self.assertTrue(started.value, 'the slow policy must actually enter decide')
            start = time.monotonic()
            for _ in range(20):
                worker.poll()
            self.assertLess(time.monotonic()-start, .5)
            worker.timeout = .03
            time.sleep(.04)
            result = worker.poll()
            self.assertIsNone(result[1])
            self.assertFalse(worker.submit(scene))
        finally:
            worker.close()

    def test_future_and_pending_previous_round_results_are_rejected(self):
        for kind in ('future', 'previous round'):
            original = World().observe('tank-1')
            worker = LateWorker()
            if kind == 'future':
                original['observation_tick'] = 2
            worker.submit(original)
            # This worker supplies one deliberately invalid delayed ticket.
            worker.poll = lambda original=original: (original, keyboard_request(original, {'w'},
                                  fire_pressed=True), 0)
            current = deepcopy(original)
            current['observation_tick'] = 1
            if kind == 'previous round':
                current['round_id'] = 2
            scheduler = AgentScheduler(worker)
            req = scheduler.request(current)
            self.assertEqual((req['throttle'], req['fire']), (0, False))
            self.assertEqual(scheduler.rejected, 1)
