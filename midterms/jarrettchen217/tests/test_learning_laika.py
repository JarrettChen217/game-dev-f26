"""Laika headless opponent uses the same native policy and resets its history."""
import unittest

from tank_game.laika import LaikaPolicy
from tank_game.learning.environment import TankDuelEnv
from tests.test_learning_environment import open_episode


class LearningLaikaTests(unittest.TestCase):
    def test_same_policy_cadence_metadata_and_transactional_restart(self):
        env = TankDuelEnv((open_episode(),),opponent='laika')
        self.addCleanup(env.close)
        _,info = env.reset(seed=0)
        first = env.controllers['tank-2'].worker.policy
        self.assertEqual(info['opponent'],'laika')
        self.assertIsInstance(first,LaikaPolicy)
        self.assertEqual(info['opponent_version'],LaikaPolicy.version)
        self.assertEqual(info['opponent_decision_hz'],20)
        for _ in range(10):
            _,_,terminated,truncated,info = env.step(8)
            self.assertEqual(info['failed_decisions'],0)
            self.assertEqual(info['rejected_decisions'],0)
            self.assertEqual(info['opponent_decisions'],2)
            if terminated or truncated:
                break
        env.reset(seed=0)
        self.assertIsNot(env.controllers['tank-2'].worker.policy,first)
        self.assertEqual(env.world.observe('tank-1')['observation_tick'],0)
