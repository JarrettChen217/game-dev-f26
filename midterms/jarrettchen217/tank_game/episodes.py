"""Immutable host setup; reuse World's validation and spawn rules."""
from dataclasses import dataclass, field

from tank_game.config import GameConfig
from tank_game.map import GameMap, Spawn, fixed_map
from tank_game.world import World


@dataclass(frozen=True)
class EpisodeSpec:
    game_map: GameMap = field(default_factory=fixed_map)
    config: GameConfig = field(default_factory=GameConfig)
    duel: bool = False
    spawns: tuple[Spawn, ...] | None = None
    round_limit: float = 120
    collision_profile: str = 'circle'

    def __post_init__(self):
        if self.spawns is not None:
            object.__setattr__(self, 'spawns', tuple(self.spawns))


def create_world(spec: EpisodeSpec) -> World:
    return World(spec.game_map, spec.config, duel=spec.duel,
                 spawns=spec.spawns, round_limit=spec.round_limit,collision_profile=spec.collision_profile)
