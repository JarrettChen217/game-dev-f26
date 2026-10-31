"""Session transitions prepare candidates before replacing owned resources."""
import unittest

from tank_game.controllers import BufferedController
from tank_game.session import GameSession
from tank_game.ui import MenuSelection


class Counted(BufferedController):
    def __init__(self):
        super().__init__()
        self.close_count = 0
    def close(self):
        self.close_count += 1
        super().close()


class OwnershipTests(unittest.TestCase):
    def test_failed_factory_preserves_old_session(self):
        candidates = []
        fail = [False]
        def first():
            item = Counted()
            candidates.append(item)
            return item
        def second():
            if fail[0]: raise RuntimeError('factory failed')
            return Counted()
        session = GameSession(MenuSelection(), seed=0,
                              controller_factories={'tank-1': first, 'tank-2': second})
        self.addCleanup(session.close)
        world, old = session.world, dict(session.controllers)
        fail[0] = True
        with self.assertRaises(RuntimeError):
            session.transition('retry', allow_active=True)
        self.assertIs(session.world, world)
        self.assertEqual(world.observe('tank-1')['round_id'], 1)
        self.assertTrue(all(c.close_count == 0 for c in old.values()))
        self.assertEqual(candidates[-1].close_count, 1)

    def test_close_is_idempotent_and_successful_retry_rebinds_runner(self):
        session = GameSession(MenuSelection(), seed=0,
                              controller_factories={'tank-1': Counted, 'tank-2': Counted})
        old = dict(session.controllers)
        self.assertTrue(session.transition('retry', allow_active=True))
        self.assertEqual(session.world.observe('tank-1')['round_id'], 2)
        self.assertTrue(all(c.close_count == 1 for c in old.values()))
        current = dict(session.controllers)
        session.runner.tick()
        session.close(); session.close()
        self.assertTrue(all(c.close_count == 1 for c in current.values()))
