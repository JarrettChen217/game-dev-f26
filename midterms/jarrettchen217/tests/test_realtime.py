"""Equal elapsed time must produce equal simulation, independent of callbacks."""

import unittest

from tank_game.agents import AgentScheduler, InlineWorker
from tank_game.app import DrivingApp
from tank_game.controllers import keyboard_request
from tank_game.map import Spawn
from tests.test_driving_app import WindowStub, confirm_result
from tests.test_duel import duel


class Clock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now


class Forward:
    def decide(self, scene):
        return keyboard_request(scene, {'w'})


class RealtimeTests(unittest.TestCase):
    def run_schedule(self, intervals, held=('w',)):
        clock, window = Clock(), WindowStub()
        world = duel(a=Spawn(80,80,0), b=Spawn(80,160,0))
        scheduler = AgentScheduler(InlineWorker(Forward()))
        # Patched clocks exercise the real adapter without needing a graphics window.
        from unittest.mock import patch
        with patch('tank_game.app.monotonic', clock, create=True):
            app = DrivingApp(window, world, scheduler=scheduler)
            window.held = set(held)
            for interval in intervals:
                clock.now += interval
                app.update()
        return app

    def test_equal_elapsed_time_moves_both_tanks_equal_distances(self):
        regular = self.run_schedule([1/60]*60)
        uneven = self.run_schedule([.01,.04,.02,.03]*10)
        self.assertEqual(regular.scene['observation_tick'], 60)
        self.assertEqual(uneven.scene['observation_tick'], 60)
        for app in (regular, uneven):
            for tank in app.scene['tanks']:
                self.assertEqual(tank['x'], 125)
            self.assertEqual(app.world.rejected_actions, 0)
            self.assertEqual(app.scheduler.decisions, 10)

    def test_turning_follows_elapsed_time_and_batched_callbacks_do_not_double_advance(self):
        regular = self.run_schedule([1/60]*30, {'d'})
        uneven = self.run_schedule([.05,0,0,0,0,0]*10, {'d'})
        self.assertEqual(regular.scene['observation_tick'], 30)
        self.assertEqual(uneven.scene['observation_tick'], 30)
        self.assertEqual(regular.scene['tanks'][0]['heading_deg'], 90)
        self.assertEqual(regular.scene['tanks'], uneven.scene['tanks'])

    def test_fire_edge_survives_callback_without_a_physics_step_and_fires_once(self):
        from unittest.mock import patch
        clock, window = Clock(), WindowStub()
        with patch('tank_game.app.monotonic', clock, create=True):
            app = DrivingApp(window, duel(), scheduler=AgentScheduler(InlineWorker(Forward())))
            window.pressed = {'f'}
            clock.now = .001
            app.update()
            self.assertEqual(app.scene['observation_tick'], 0)
            window.pressed.clear()
            clock.now = .101
            app.update()
            self.assertEqual(len(app.scene['bullets']), 1)
            self.assertEqual(app.world.rejected_actions, 0)

    def test_long_pause_does_not_teleport_or_leave_catchup_debt(self):
        app = self.run_schedule([10,0,1/60])
        self.assertLessEqual(app.scene['observation_tick'], 16)
        self.assertLessEqual(app.scene['tanks'][0]['x'], 92)

    def test_round_end_during_catchup_and_restart_clear_old_time_and_controls(self):
        clock, window = Clock(), WindowStub()
        world = duel(round_limit=3/60)
        app = DrivingApp(window, world, clock=clock,
                         scheduler=AgentScheduler(InlineWorker(Forward())))
        window.held = {'w'}
        clock.now = .151
        app.update()
        self.assertEqual(app.scene['round_status'], 'GAME_OVER')
        self.assertEqual(app.scene['observation_tick'], 3)
        self.assertEqual(world.rejected_actions, 0)
        clock.now += .001
        confirm_result(window, app)
        self.assertEqual(app.scene['round_id'], 2)
        self.assertEqual(app.scene['observation_tick'], 0)
        window.pressed.clear()
        clock.now += .001
        app.update()
        self.assertEqual(app.scene['observation_tick'], 0)
        clock.now += 1/60
        app.update()
        self.assertEqual(world._tanks['tank-1'].x, 100)
        self.assertEqual(world.rejected_actions, 0)
