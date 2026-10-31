"""Selectable policies share physics and restart with fresh strategy memory."""

import subprocess
import sys
import unittest
from unittest.mock import patch

from tank_game.agents import AgentScheduler, InlineWorker
from tank_game.app import DrivingApp
from tank_game.patrol import SimplePatrol
from tank_game.prediction import HardPolicy
from tank_game.strategies import make_policy
from tests.test_driving_app import WindowStub, confirm_result
from tests.test_duel import duel


class StrategyTests(unittest.TestCase):
    def test_factory_preserves_baseline_and_rejects_unknown_names(self):
        self.assertIsInstance(make_policy('simple'),SimplePatrol)
        self.assertIsInstance(make_policy('hard'),HardPolicy)
        self.assertIsNot(make_policy('hard'),make_policy('hard'))
        with self.assertRaises(ValueError):
            make_policy('anything')

    def test_each_mode_restarts_its_owned_policy_and_changes_active_title(self):
        for mode in ('simple','hard'):
            window=WindowStub()
            with patch('tank_game.process_worker.ProcessWorker',
                       lambda policy,timeout:InlineWorker(policy)):
                app=DrivingApp(window,duel(round_limit=1/60),
                               strategy=mode,clock=window.clock)
                first=app.scheduler.worker.policy
                app.update()
                self.assertEqual(app.scene['round_status'],'GAME_OVER')
                confirm_result(window, app)
                self.assertIsNot(first,app.scheduler.worker.policy)
                self.assertIsInstance(app.scheduler,AgentScheduler)
                self.assertIn(mode.capitalize(),window.init_options['title'])
                self.assertEqual(app.strategy,mode)
                app.close()

    def test_cli_accepts_both_modes_and_requires_duel_for_selection(self):
        for mode in ('simple','hard'):
            result=subprocess.run([sys.executable,'-m','tank_game','--duel',
                                   '--strategy',mode,'--inspect'],capture_output=True,text=True,
                                  check=False)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('tank-2',result.stdout)
        result=subprocess.run([sys.executable,'-m','tank_game','--strategy','hard'],
                              capture_output=True,text=True,check=False)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('--duel',result.stderr)
