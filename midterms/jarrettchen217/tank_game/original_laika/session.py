"""Host lifecycle for original generated mazes; never a second simulator."""
from dataclasses import dataclass

from tank_game.original_laika.world import OriginalWorld


@dataclass(frozen=True)
class OriginalRecord:
    seed: int
    generator_version: str = 'killfield-original-wasm'


class OriginalRoundSession:
    def __init__(self, seed=1000):
        self.world = OriginalWorld(seed)
        self.record = OriginalRecord(seed)
        self.last_error = None

    def transition(self, operation, *, allow_active=False):
        if operation not in ('retry','next_map'):
            raise ValueError('choose retry or next_map')
        seed = self.record.seed if operation == 'retry' else (self.record.seed+1) % 2**32
        changed = self.world.restart(seed=seed, allow_active=allow_active)
        if changed:
            self.record = OriginalRecord(seed)
        return changed

    def close(self):
        self.world.close()
