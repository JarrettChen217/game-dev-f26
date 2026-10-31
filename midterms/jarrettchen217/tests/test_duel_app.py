"""Duel launch, state-scoped input and reproducible real-simulation smoke runs."""

import subprocess
import sys
import unittest
from unittest.mock import patch

from tank_game.agents import AgentScheduler, InlineWorker
from tank_game.app import DrivingApp
from tank_game.baseline import run_baseline
from tank_game.patrol import SimplePatrol
from tank_game.world import World
from tests.test_driving_app import WindowStub, confirm_result
from tests.test_duel import duel


class DuelAppTests(unittest.TestCase):
    def test_both_controllers_move_and_restart_clears_round_intentions(self):
        window = WindowStub()
        world = duel(round_limit=3/60)
        scheduler = AgentScheduler(InlineWorker(SimplePatrol()))
        app = DrivingApp(window, world, scheduler=scheduler, clock=window.clock)
        window.held = {'w'}
        for _ in range(3):
            app.update()
        self.assertEqual(app.scene['round_status'], 'GAME_OVER')
        self.assertEqual(app.scene['duel']['result'], 'draw')
        self.assertGreater(world._tanks['tank-1'].x, 100)
        confirm_result(window, app)
        self.assertEqual(app.scene['round_id'], 2)
        self.assertEqual(app.scene['observation_tick'], 0)
        self.assertEqual(len(app.scene['tanks']), 2)
        window.pressed.clear()
        app.update()
        self.assertEqual(world._tanks['tank-1'].x, 100)
        self.assertEqual(world.rejected_actions, 0)
        window.pressed = {'esc'}
        app.update()
        self.assertFalse(window.exited)
        self.assertEqual(app.ui.screen, 'pause')

    def test_cli_duel_inspection_exposes_two_tanks_and_public_result(self):
        result = subprocess.run([sys.executable, '-m', 'tank_game', '--duel', '--inspect'],
                                capture_output=True, text=True, check=True)
        self.assertIn('tank-2', result.stdout)
        self.assertIn('"result": null', result.stdout)

    def test_baseline_run_is_real_repeatable_and_restarts_finished_rounds(self):
        a, b = run_baseline(steps=2400), run_baseline(steps=2400)
        for report in (a, b):
            self.assertGreater(report['live_steps'], 0)
            self.assertGreater(report['projectile_steps'], 0)
            self.assertEqual(report['invalid_actions'], 0)
            self.assertGreater(report['decisions'], 0)
            self.assertGreater(report['restarts'], 0)
        self.assertEqual(a['action_digest'], b['action_digest'])
        self.assertEqual(a['round_results'], b['round_results'])

    def test_duel_body_identifiers_and_round_metadata_remain_detached(self):
        w = World(duel=True)
        before = w.observe('tank-2')
        s = w.observe('tank-2')
        s['duel']['result'] = 'tank-2'
        s['tanks'][0]['x'] = -999
        self.assertEqual(w.observe('tank-2'), before)

    def test_smoke_report_counts_rejected_requests_across_restarts(self):
        class RejectedInputWorld(World):
            injected = 0

            def submit_action(self, source, data):
                type(self).injected += 1
                super().submit_action(source, dict(data, turn=2))
                return super().submit_action(source, data)

        with patch('tank_game.episodes.World', RejectedInputWorld):
            report = run_baseline(steps=2400)
        self.assertGreater(report['restarts'], 0)
        self.assertEqual(report['invalid_actions'], RejectedInputWorld.injected)
