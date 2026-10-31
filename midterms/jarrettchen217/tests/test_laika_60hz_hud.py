"""Thin source60Hz integration of the unchanged shared match HUD."""
import platform
import sys
import unittest

from tank_game.app import DrivingApp
from tests.test_original_laika_app import OriginalWindow
from tests.test_realtime import Clock


@unittest.skipUnless(sys.platform == 'darwin' and platform.machine() == 'arm64',
                     'optional source60Hz artifact currently targets macOS arm64')
class Source60HudTests(unittest.TestCase):
    def app(self):
        from tank_game.laika_60hz.session import Source60RoundSession
        session = Source60RoundSession(1000)
        self.addCleanup(session.close)
        window, clock = OriginalWindow(), Clock()
        app = DrivingApp(window, strategy='laika', random_session=session, clock=clock)
        self.addCleanup(app.close)
        return session, window, clock, app

    def advance(self, clock, app):
        clock.now += 1/60
        app.update()

    def test_source_terminal_counts_once_without_adding_rust_score_again(self):
        session, window, clock, app = self.app()
        self.assertIsNotNone(getattr(app, 'match_score', None), 'source60Hz needs the shared session ledger')
        settling = False
        for _ in range(1200):
            self.advance(clock, app)
            if app.scene['round_phase'] == 'settling':
                settling = True
                self.assertEqual(app.match_score.points, {'tank-1': 0, 'tank-2': 0})
            if app.scene['round_status'] == 'GAME_OVER':
                break
        self.assertTrue(settling)
        self.assertEqual(app.scene['duel']['result'], 'tank-2')
        self.assertIs(app.match_score, session.score)
        for _ in range(5):
            self.advance(clock, app)
            app.draw()
        self.assertEqual(app.match_score.points, {'tank-1': 0, 'tank-2': 1})
        self.assertTrue(any('YOU 0 : 1 Laika' in text for _, _, text, _ in window.texts))

    def test_unobserved_terminal_retry_and_new_map_retain_the_same_score(self):
        session, _, _, app = self.app()
        self.assertIsNotNone(getattr(app, 'match_score', None))
        score = app.match_score
        for _ in range(1200):
            session.world.step()
            if session.world.observe('tank-1')['round_status'] == 'GAME_OVER':
                break
        # Transition must record a result even before a window update sees it.
        self.assertTrue(session.transition('retry'))
        self.assertEqual(score.points, {'tank-1': 0, 'tank-2': 1})
        self.assertTrue(session.transition('next_map', allow_active=True))
        self.assertIs(session.score, score)
        self.assertEqual(score.points, {'tank-1': 0, 'tank-2': 1})
        self.assertEqual(session.world.observe('tank-1')['round_id'], 3)

    def test_actual_settlement_pause_and_draw_are_read_only(self):
        _, window, clock, app = self.app()
        self.assertIsNotNone(getattr(app, 'match_score', None))
        for _ in range(1200):
            self.advance(clock, app)
            if app.scene['round_phase'] == 'settling':
                break
        before = app.world.raw_render
        actor_before = app.world.observe('tank-1')
        app.draw()
        self.assertTrue(any('3.0s' in text and 'Laika alive' in text for _, _, text, _ in window.texts))
        self.assertEqual(app.world.raw_render, before)
        self.assertEqual(app.world.observe('tank-1'), actor_before)
        window.pressed, window.held = {'esc'}, {'esc'}
        self.advance(clock, app)
        window.pressed, window.held = set(), set()
        facts = app.world.presentation_facts()
        for _ in range(5):
            clock.now += 1
            app.update()
            app.draw()
        self.assertEqual(app.world.presentation_facts(), facts)
        self.assertEqual(app.match_score.points, {'tank-1': 0, 'tank-2': 0})
        for x, y, width, height, *_ in window.rectangles:
            if y == 442:
                self.assertGreaterEqual(x, 204)
                self.assertLessEqual(x+width, 716)
                self.assertLessEqual(y+height, 454)

    def test_quit_clears_points_and_new_session_starts_zero(self):
        session, window, clock, app = self.app()
        self.assertIsNotNone(getattr(app, 'match_score', None))
        for _ in range(1200):
            session.world.step()
            if session.world.observe('tank-1')['round_status'] == 'GAME_OVER':
                break
        session.transition('retry')
        self.assertEqual(app.match_score.points['tank-2'], 1)
        app.ui.screen = 'pause'
        app._menu_operation = lambda now: 'quit'  # UI input only; real close lifecycle
        app._results_update(clock.now)
        self.assertEqual(app.match_score.points, {'tank-1': 0, 'tank-2': 0})
        self.assertTrue(window.exited)
        fresh, _, _, _ = self.app()
        self.assertEqual(fresh.score.points, {'tank-1': 0, 'tank-2': 0})


class Source60ProjectionTests(unittest.TestCase):
    def test_projection_maps_real_seat_ids_and_second_death_reset_without_awarding_draw(self):
        from tank_game.laika_60hz.hud import match_facts
        from tank_game.match_hud import SessionScore, settlement_primitives
        facts = {'round_id': 7, 'round_phase': 'settling', 'survivors': ['tank-1'],
                 'settlement': {'remaining_seconds': 1.5, 'total_seconds': 3.},
                 'result': None, 'source_seats': {'tank-1': 1, 'tank-2': 0},
                 'round_scores': {'tank-1': 9, 'tank-2': 11}}
        score = SessionScore(('tank-1', 'tank-2'))
        score.record(match_facts(facts))
        facts.update(survivors=[], settlement={'remaining_seconds': 3., 'total_seconds': 3.})
        reset = match_facts(facts)
        self.assertEqual(reset.remaining_seconds, 3.)
        primitives = settlement_primitives((('tank-1', 'YOU'), ('tank-2', 'Laika')), reset,
                                           (0, 438, 512, 16))
        self.assertIn('Both destroyed', primitives[-1][3])
        facts.update(round_phase='frozen', result='draw')
        for _ in range(3):
            score.record(match_facts(facts))
        self.assertEqual(score.points, {'tank-1': 0, 'tank-2': 0})
        facts.update(round_id=8, result='tank-1', survivors=['tank-1'])
        score.record(match_facts(facts))
        self.assertEqual(score.points, {'tank-1': 1, 'tank-2': 0})


if __name__ == '__main__':
    unittest.main()
