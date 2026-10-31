"""Native selection, desktop isolation and the same headless Laika opponent."""
import json
import subprocess
import sys
import unittest
from unittest.mock import patch

from tank_game.agents import InlineWorker
from tank_game.app import DrivingApp
from tank_game.runtime_factories import create_desktop_scheduler
from tank_game.ui import UIState
from tank_game.ui_layout import menu_controls
from tests.test_driving_app import WindowStub, confirm_result
from tests.test_duel import duel


class LaikaIntegrationTests(unittest.TestCase):
    def test_cli_can_inspect_laika_without_loading_native_or_learning(self):
        result = subprocess.run([sys.executable,'-m','tank_game','--duel','--strategy',
                                 'laika','--inspect'],capture_output=True,text=True,check=False)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(len(json.loads(result.stdout)['tanks']),2)

    def test_menu_keyboard_and_pointer_can_select_all_four_opponents(self):
        ui = UIState()
        choices = [c for c in menu_controls(ui) if c.focus=='strength' and c.value]
        self.assertEqual([c.value for c in choices], ['simple','hard','laika','hybrid'])
        ui.focus = 'strength'
        ui.handle('right',0)
        self.assertEqual(ui.selection.strategy,'hard')
        ui.handle('right',1)
        self.assertEqual(ui.selection.strategy,'laika')
        ui.handle('left',2)
        self.assertEqual(ui.selection.strategy,'hard')
        ui.activate('strength',3,value='laika')
        self.assertEqual(ui.selection.effective(),(True,'laika',True))

    def test_desktop_factory_uses_bounded_worker_and_laika_host_cadence(self):
        with patch('tank_game.process_worker.ProcessWorker',
                   lambda policy,timeout:InlineWorker(policy,timeout=timeout)):
            scheduler = create_desktop_scheduler('laika')
            self.addCleanup(scheduler.close)
            self.assertEqual(scheduler.decision_hz,20)
            self.assertEqual(scheduler.worker.timeout,.25)

    def test_game_restart_replaces_owned_laika_policy(self):
        window = WindowStub()
        with patch('tank_game.process_worker.ProcessWorker',
                   lambda policy,timeout:InlineWorker(policy,timeout=timeout)):
            app = DrivingApp(window,duel(round_limit=1/60),strategy='laika',clock=window.clock)
            self.addCleanup(app.close)
            policy = app.scheduler.worker.policy
            app.update()
            confirm_result(window,app)
            self.assertIsNot(app.scheduler.worker.policy,policy)
            self.assertEqual(app.strategy,'laika')
            self.assertIn('Laika',window.init_options['title'])

    def test_policy_timer_uses_observation_time_in_a_25hz_profile(self):
        from tank_game.laika import LaikaPolicy
        policy = LaikaPolicy(decision_hz=25)
        scene = duel().observe('tank-1')
        scene['rules']['tick_rate'] = 25
        policy.decide(scene)
        # Missing intermediate requests consume their elapsed time, not one frame.
        scene['observation_tick'] = 15
        policy.decide(scene)
        self.assertAlmostEqual(policy.goal.period,0)
        scene['observation_tick'] = 16
        policy.decide(scene)
        self.assertEqual(policy.goal.kind,'shoot')

    def test_menu_describes_laika_instead_of_the_hard_policy(self):
        from tank_game.ui_rendering import draw_menu
        from tests.test_ui_rendering import FakeWindow
        window = FakeWindow()
        app = DrivingApp(window,menu=True,clock=window.clock)
        self.addCleanup(app.close)
        app.ui.selection.strategy = 'laika'
        draw_menu(window,app.ui,app.keymap,0)
        self.assertTrue(any('Laika:' in entry[2] for entry in window.texts))
        self.assertFalse(any('Hard:' in entry[2] for entry in window.texts))

