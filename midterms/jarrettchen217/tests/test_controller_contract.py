"""Input survives render-only frames and belongs to one environment/player."""
import unittest

from tank_game.actions import Action
from tank_game.world import World


class ControllerContractTests(unittest.TestCase):
    def test_fire_survives_render_only_frames_and_is_consumed_once(self):
        from tank_game.controllers import BufferedController
        buffer = BufferedController()
        scene = World().observe('tank-1')
        buffer.set_input(Action(1, 0, True))
        buffer.set_input(Action(-1, 1, False))
        first = buffer.request(scene)
        self.assertEqual((first['throttle'], first['turn'], first['fire']), (-1, 1, True))
        self.assertFalse(buffer.request(scene)['fire'])
        self.assertEqual(buffer.request(scene)['throttle'], -1)

    def test_pause_terminal_and_close_clear_input(self):
        from tank_game.controllers import BufferedController
        buffer = BufferedController()
        scene = World().observe('tank-1')
        for clear in ('pause', 'terminal', 'dead', 'close'):
            with self.subTest(clear=clear):
                buffer = BufferedController()
                buffer.set_input(Action(1, 1, True))
                bad = World().observe('tank-1')
                if clear == 'pause':
                    buffer.pause(scene)
                elif clear == 'terminal':
                    bad['round_status'] = 'DYING'
                    buffer.request(bad)
                elif clear == 'dead':
                    bad['self_status']['alive'] = False
                    buffer.request(bad)
                else:
                    buffer.close()
                    buffer.close()
                    with self.assertRaises(RuntimeError):
                        buffer.set_input(Action())
                request = buffer.request(scene)
                self.assertEqual((request['throttle'], request['turn'], request['fire']), (0, 0, False))
                self.assertEqual(request['tank_id'], scene['self_id'])

    def test_separate_players_do_not_share_buffer(self):
        from tank_game.controllers import BufferedController
        a, b = BufferedController(), BufferedController()
        scene = World().observe('tank-1')
        a.set_input(Action(1, 0, True))
        self.assertFalse(b.request(scene)['fire'])
        self.assertTrue(a.request(scene)['fire'])
