"""Owned sessions reuse real worlds and close decision resources."""
import unittest
from unittest.mock import patch

from tank_game.agents import AgentScheduler, InlineWorker
from tank_game.random_maps import GenerationError
from tank_game.session import GameSession
from tank_game.strategies import make_policy
from tank_game.ui import MenuSelection


class SessionTests(unittest.TestCase):
    def factory(self):
        return AgentScheduler(InlineWorker(make_policy('simple')))

    def test_retry_uses_same_map_and_fresh_decision_state(self):
        session = GameSession(MenuSelection(), source60=False, seed=17, scheduler_factory=self.factory)
        self.addCleanup(session.close)
        old = session.random_session.record
        scheduler = session.scheduler
        with (patch.object(session.world, 'observe', return_value={'round_status': 'GAME_OVER'}),
              patch.object(session.world, 'restart', return_value=True)):
            self.assertTrue(session.transition('retry'))
        self.assertEqual(session.random_session.record, old)
        self.assertIsNot(session.scheduler, scheduler)

    def test_failed_new_map_preserves_session(self):
        session = GameSession(MenuSelection(), source60=False, seed=17, scheduler_factory=self.factory)
        self.addCleanup(session.close)
        old, world, scheduler = session.random_session.record, session.world, session.scheduler
        with (patch.object(world, 'observe', return_value={'round_status': 'GAME_OVER'}),
              patch('tank_game.random_rounds.generate_random_map',
                    side_effect=GenerationError(18, ('forced',)))):
            self.assertFalse(session.transition('next_map'))
        self.assertIs(session.world, world)
        self.assertIs(session.scheduler, scheduler)
        self.assertEqual(session.random_session.record, old)
        self.assertIn('forced', session.random_session.last_error)

    def test_close_twice_closes_worker_once(self):
        session = GameSession(MenuSelection(), source60=False, seed=17, scheduler_factory=self.factory)
        with patch.object(session.scheduler, 'close', wraps=session.scheduler.close) as close:
            session.close()
            session.close()
            self.assertEqual(close.call_count, 1)

    def test_single_tank_cannot_launch_random_or_worker(self):
        session = GameSession(MenuSelection(bot_enabled=False), scheduler_factory=self.factory)
        self.assertIsNone(session.scheduler)
        self.addCleanup(session.close)
        self.assertFalse(session.random_session.random_map)
        self.assertIsNone(session.random_session.score)
        self.assertNotIn('duel', session.world.observe('tank-1'))
