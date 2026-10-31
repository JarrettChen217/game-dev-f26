"""Host map transitions must be atomic and reject stale round intentions."""
import unittest
from unittest.mock import patch

from tank_game.controllers import keyboard_request
from tank_game.random_maps import GenerationError


class RandomRoundTests(unittest.TestCase):
    def test_retry_preserves_map_but_next_map_changes_walls_and_round_id(self):
        from tank_game.random_rounds import RandomRoundSession
        session = RandomRoundSession(17, round_limit=1/60)
        old = session.world.observe('tank-1')
        old_request = keyboard_request(old, set(), fire_pressed=True)
        initial = session.record
        self.assertFalse(session.transition('next_map'))
        session.world.step()
        self.assertTrue(session.transition('retry'))
        self.assertEqual(session.record, initial)
        self.assertEqual(session.world.observe('tank-1')['tanks'], old['tanks'])
        session.world.step()
        self.assertTrue(session.transition('next_map'))
        self.assertNotEqual(session.record.layout_id, initial.layout_id)
        current = session.world.observe('tank-1')
        self.assertEqual((current['round_id'], current['observation_tick']), (3, 0))
        session.world.submit_action('tank-1', old_request)
        self.assertEqual(session.world.rejected_actions, 1)

    def test_failed_generation_leaves_world_and_record_untouched(self):
        from tank_game.random_rounds import RandomRoundSession
        session = RandomRoundSession(4294967295, round_limit=1/60)
        session.world.step()
        old_scene, old_record = session.world.observe('tank-1'), session.record
        with patch('tank_game.random_rounds.generate_random_map',
                   side_effect=GenerationError(0, ['invalid'])):
            self.assertFalse(session.transition('next_map'))
        self.assertEqual(session.world.observe('tank-1'), old_scene)
        self.assertEqual(session.record, old_record)
        self.assertIn('seed 0', session.last_error)
        self.assertTrue(session.transition('next_map'))
        self.assertEqual(session.record.seed, 0)

    def test_invalid_world_replacement_does_not_destroy_finished_state(self):
        from dataclasses import replace

        from tank_game.random_rounds import RandomRoundSession
        from tests.test_map import room
        session = RandomRoundSession(7, round_limit=1/60)
        session.world.step()
        old = session.world.observe('tank-1')
        invalid = replace(room(8, 6), edges=room(8, 6).edges[:-1])
        with self.assertRaises(ValueError):
            session.world.restart(game_map=invalid)
        self.assertEqual(session.world.observe('tank-1'), old)
