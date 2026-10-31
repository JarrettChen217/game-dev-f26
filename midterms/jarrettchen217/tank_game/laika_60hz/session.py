"""Generated source maze lifecycle for the60Hz profile."""
from tank_game.laika_60hz.hud import SEATS, match_facts
from tank_game.laika_60hz.world import World60
from tank_game.match_hud import SessionScore
from tank_game.original_laika.session import OriginalRecord, OriginalRoundSession


class Source60RoundSession(OriginalRoundSession):
    def __init__(self, seed=1000):
        self.world = World60(seed)
        self.record = OriginalRecord(seed, 'killfield-source-60hz')
        self.last_error = None
        self.score = SessionScore(tuple(seat for seat, _name in SEATS))
        self._closed = False

    def record_result(self):
        facts = match_facts(self.world.presentation_facts())
        if not self._closed:
            self.score.record(facts)
        return facts

    def transition(self, operation, *, allow_active=False):
        if self._closed:
            return False
        self.record_result()
        changed = super().transition(operation, allow_active=allow_active)
        if changed:
            self.record = OriginalRecord(self.world.seed, 'killfield-source-60hz')
        return changed

    def close(self):
        self._closed = True
        self.score.clear()
        super().close()
