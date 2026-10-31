"""Mac play wiring; fake policy, no model games or training."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ModelIdentityTests(unittest.TestCase):
    def test_checkpoint_hash_is_checked_before_loading_tensors(self):
        from tank_game.laika_60hz.mac_play import verified_checkpoint
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            verified_checkpoint(ROOT/'pyproject.toml')


@unittest.skipUnless((ROOT/'reports/source60-hybrid/mac-play/native/play.dylib').exists(),
                     'build the isolated Mac play library first')
class PlayBoundaryTests(unittest.TestCase):
    def world(self, mode='human'):
        from tank_game.laika_60hz.mac_play import HybridPlayWorld
        class Policy:
            calls = 0
            def action(self, features, mask):
                self.calls += 1
                return 8
        p = Policy()
        w = HybridPlayWorld(17, policy=p, mode=mode)
        self.addCleanup(w.close)
        return w, p

    def test_observe_draw_and_pause_never_advance_policy_or_simulator(self):
        w, p = self.world()
        for _ in range(3):
            w.observe('tank-1'); w.presentation_facts()
        self.assertEqual(p.calls, 0)
        w.step()
        self.assertEqual((p.calls, w.observe('tank-1')['observation_tick']), (1, 1))
        w.observe('tank-1')
        self.assertEqual(p.calls, 1)
        self.assertEqual(w.diagnostics['laika_calls'], 0)
        self.assertEqual(w.observe('tank-1')['controller_roles']['tank-2'], 'hybrid-u19588')

    def test_app_pause_restart_and_labels_use_the_learned_opponent(self):
        from tank_game.app import DrivingApp
        from tank_game.laika_60hz.mac_play import HybridPlaySession
        from tests.test_original_laika_app import OriginalWindow
        from tests.test_realtime import Clock
        w, p = self.world()
        session = HybridPlaySession(world=w)
        window, clock = OriginalWindow(), Clock()
        app = DrivingApp(window, strategy='laika', random_session=session, clock=clock)
        self.addCleanup(app.close)
        app.ui.screen, app.ui.focus = 'pause', 'resume'
        clock.now += 5
        app.update(); app.draw()
        self.assertEqual(p.calls, 0)
        self.assertTrue(any('u19588' in t[2].lower() for t in window.texts))
        self.assertFalse(any(t[2].startswith('Laika /') for t in window.texts))
        app.ui.screen = 'playing'
        clock.now += 1/60
        app.update()
        self.assertEqual(p.calls, 1)
        self.assertTrue(session.transition('retry', allow_active=True))
        self.assertEqual(w.observe('tank-1')['observation_tick'], 0)
        self.assertEqual(p.calls, 1)

    def test_watch_observation_history_matches_retained_training(self):
        import numpy as np

        from tank_game.laika_60hz.training.environment import Source60HybridEnv
        w, _ = self.world('watch')
        e = Source60HybridEnv(); self.addCleanup(e.close)
        e.reset(seed=17)
        for _ in range(3):
            np.testing.assert_array_equal(w._bridge.features, e.observe()['features'])
            np.testing.assert_array_equal(w._bridge.mask, e.observe()['mask'])
            w.step(); e.step(8)
        self.assertEqual(w.diagnostics['laika_calls'], 3)

    def test_watch_labels_do_not_offer_human_driving_controls(self):
        from tank_game.app import DrivingApp
        from tank_game.laika_60hz.mac_play import HybridPlaySession
        from tests.test_original_laika_app import OriginalWindow
        w, _ = self.world('watch')
        session = HybridPlaySession(world=w)
        window = OriginalWindow()
        app = DrivingApp(window, strategy='laika', random_session=session)
        self.addCleanup(app.close)
        app.draw()
        self.assertTrue(any('WATCH' in t[2] for t in window.texts))
        self.assertFalse(any('drive' in t[2] for t in window.texts))
