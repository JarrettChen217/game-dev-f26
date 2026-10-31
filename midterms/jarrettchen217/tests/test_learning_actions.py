"""The learning codec covers the actual game's joint action capability."""
import unittest

from tank_game.actions import Action

try:
    from tank_game.learning.actions import decode_action, encode_action
except ImportError:
    decode_action=encode_action=None


class LearningActionTests(unittest.TestCase):
    def test_joint_capability_round_trip_and_strict_values(self):
        self.assertIsNotNone(decode_action,'learning codec missing')
        seen=set()
        for throttle in (-1,0,1):
            for turn in (-1,0,1):
                for fire in (False,True):
                    action=Action(throttle,turn,fire)
                    code=encode_action(action)
                    seen.add(code)
                    self.assertEqual(decode_action(code),action)
        self.assertEqual(seen,set(range(18)))
        self.assertEqual(encode_action(Action()),8)
        self.assertEqual(decode_action(0),Action(-1,-1,False))
        self.assertEqual(decode_action(17),Action(1,1,True))
        for invalid in (-1,18,True,8.0,None):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):decode_action(invalid)
