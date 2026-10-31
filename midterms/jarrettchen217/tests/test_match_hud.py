"""Portable score/HUD contract, independent of engine or window libraries."""
import unittest

from tank_game.match_hud import MatchFacts, SessionScore, score_primitives, settlement_primitives

NAMES = (('player', 'YOU'), ('bot', 'Hybrid'))


class MatchHudTests(unittest.TestCase):
    def test_only_final_results_count_once_with_no_draw_points(self):
        score = SessionScore(('player', 'bot'))
        score.record(MatchFacts(1, 'settling', ('player',), 1.2, 3, 'player'))
        self.assertEqual(score.points, {'player': 0, 'bot': 0})
        for _ in range(4):
            score.record(MatchFacts(1, 'finished', winner_id='player'))
        score.record(MatchFacts(2, 'finished', winner_id='bot'))
        score.record(MatchFacts(3, 'finished'))
        score.record(MatchFacts(1, 'finished', winner_id='player'))
        self.assertEqual(score.points, {'player': 1, 'bot': 1})
        score.clear()
        self.assertEqual(score.points, {'player': 0, 'bot': 0})
        score.record(MatchFacts(1, 'finished', winner_id='bot'))
        self.assertEqual(score.points['bot'], 1)

    def test_drawing_is_idempotent_and_labels_use_stable_seats(self):
        score = SessionScore(('player', 'bot'))
        score.record(MatchFacts(1, 'finished', winner_id='bot'))
        for _ in range(3):
            primitives = score_primitives(NAMES, score.points, (144, 426, 200, 8))
        self.assertIn('YOU 0 : 1 Hybrid', primitives[0])
        self.assertEqual(score.points, {'player': 0, 'bot': 1})
        self.assertIn('Laika', score_primitives((NAMES[0], ('bot', 'Laika')), score.points,
                                              (0, 0, 200, 8))[0][3])

    def test_settlement_uses_supplied_engine_seconds_and_progress(self):
        facts = MatchFacts('round-a', 'settling', ('player',), 1.2, 3)
        primitives = settlement_primitives(NAMES, facts, (0, 0, 200, 16))
        self.assertIn(('rect', 1, 1, 119, 2, 10), primitives)
        text = primitives[-1][3]
        self.assertIn('YOU alive', text)
        self.assertIn('1.2s', text)
        self.assertNotIn('win', text.lower())
        self.assertIn('0.1s', settlement_primitives(NAMES,
            MatchFacts(1, 'settling', ('bot',), .01, 2.5), (0, 0, 200, 16))[-1][3])

    def test_both_dead_and_absent_settlement_never_promise_a_score(self):
        text = settlement_primitives(NAMES, MatchFacts(1, 'settling', (), 2, 3),
                                     (0, 0, 300, 16))[-1][3]
        self.assertIn('Both destroyed', text)
        self.assertIn('no points', text)
        for facts in (MatchFacts(1, 'playing'), MatchFacts(1, 'finished'),
                      MatchFacts(1, 'settling')):
            self.assertEqual(settlement_primitives(NAMES, facts, (0, 0, 300, 16)), ())

    def test_large_score_type_fits_and_status_can_use_compact_spacing(self):
        primitives = score_primitives(NAMES, {'player': 12, 'bot': 34},
                                      (150, 426, 200, 16), scale=2)
        _, x, y, text, _ = primitives[0]
        self.assertEqual(text, 'YOU 12 : 34 Hybrid')
        self.assertGreaterEqual(x, 150)
        self.assertLessEqual(x+8*len(text), 350)
        self.assertEqual(y, 426)
        status = settlement_primitives(NAMES,
            MatchFacts(1, 'settling', ('player',), 1.2, 3),
            (0, 442, 512, 14), text_gap=6)[-1]
        self.assertEqual(status[2], 448)
        self.assertLessEqual(status[2]+8, 456)

    def test_long_names_and_scores_fit_the_assigned_bounds(self):
        primitives = score_primitives((('p', 'Player name much too long'),
                                       ('b', 'Reference model name')), {'p': 123, 'b': 456},
                                      (150, 426, 190, 8))
        _, x, y, text, _ = primitives[0]
        self.assertGreaterEqual(x, 150)
        self.assertLessEqual(x + len(text)*4, 340)
        self.assertEqual(y, 426)
