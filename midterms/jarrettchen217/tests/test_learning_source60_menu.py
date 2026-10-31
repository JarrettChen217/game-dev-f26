"""Normal entrypoint/menu and native-focus regression for the learned Mac opponent."""
import unittest
from unittest.mock import patch

from tank_game.ui import UIState
from tank_game.window_state import RawWindow
from tests.test_original_laika_app import OriginalWindow
from tests.test_realtime import Clock


class FakePolicy:
    calls = 0
    def action(self, features, mask):
        self.calls += 1
        return 8


class HybridEntryTests(unittest.TestCase):
    def test_keyboard_can_select_hybrid_as_the_fourth_bot(self):
        ui = UIState(); ui.focus = 'strength'
        for _ in range(3): ui.handle('right',0)
        self.assertEqual(ui.selection.strategy, 'hybrid')
        self.assertEqual(ui.selection.effective(), (True,'hybrid',True))

    def test_normal_menu_starts_hybrid_in_native_sixty_hz_and_closes_it(self):
        from tank_game.app import DrivingApp
        from tank_game.window_state import NativeWindowObserver
        window,clock = OriginalWindow(),Clock()
        with patch('tank_game.laika_60hz.mac_play.ReleasedPolicy',return_value=FakePolicy()):
            app = DrivingApp(window,menu=True,clock=clock,
                    window_observer=NativeWindowObserver(reader=lambda: RawWindow(True,(920,464),(100,100),(1,))))
            self.addCleanup(app.close)
            app.ui.selection.strategy='hybrid';app.ui.selection.random_map=False;app.ui.focus='start'
            window.pressed,window.held={'enter'},{'enter'}
            clock.now+=.01;app.update()
            window.pressed,window.held=set(),set()
            clock.now+=.2;app.update()
            self.assertIsNotNone(app.world)
            self.assertTrue(app._source60_engine)
            self.assertTrue(app._original_engine)
            self.assertIsNone(app.scheduler)
            self.assertEqual(list(app.runner.controllers),['tank-1'])
            self.assertEqual(app.world.observe('tank-1')['controller_roles']['tank-2'],'hybrid-u19588')
            app.ui.screen='pause'; window.texts.clear(); app.draw()
            self.assertTrue(any('Fixed map' in t[2] for t in window.texts))
            self.assertFalse(any('Random / Seed:' in t[2] or 'NEXT MAP' in t[2] for t in window.texts))
            self.assertFalse(app.session.transition('next_map',allow_active=True))
            world=app.world;app.close()
            self.assertIsNone(world._bridge.handle)

    def test_direct_hybrid_cli_honors_random_map(self):
        from unittest.mock import MagicMock

        from tank_game.__main__ import main
        session=MagicMock()
        with (patch('sys.argv',['tank_game','--duel','--strategy','hybrid','--random-map']),
              patch('tank_game.session.GameSession',return_value=session) as factory,
              patch('tank_game.app.main')):
            main()
            self.assertTrue(factory.call_args.args[0].random_map)
            self.assertIsNone(factory.call_args.kwargs['seed'])
