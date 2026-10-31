"""Host-owned random-map lifecycle; only validated transitions change the round."""
from tank_game.config import GameConfig
from tank_game.episodes import EpisodeSpec, create_world
from tank_game.random_maps import DEFAULT_OPTIONS, GenerationError, generate_random_map


class RandomRoundSession:
    def __init__(self, seed, *, config=None, round_limit=120, options=DEFAULT_OPTIONS, collision_profile='circle'):
        self.config = config if config is not None else GameConfig()
        self.options = options
        self.record = generate_random_map(seed, radius=self.config.tank_radius, options=options)
        self.world = create_world(EpisodeSpec(self.record.maze, self.config, True,
                                               self.record.spawns, round_limit,collision_profile))
        self.last_error = None

    def transition(self, operation: str, *, allow_active=False) -> bool:
        if operation not in ('retry', 'next_map'):
            raise ValueError('select retry or next_map')
        if self.world.observe('tank-1')['round_status'] != 'GAME_OVER' and not allow_active:
            return False
        if operation == 'retry':
            result = self.world.restart(allow_active=allow_active)
        else:
            try:
                candidate = generate_random_map((self.record.seed+1) % 2**32,
                                                radius=self.config.tank_radius,
                                                options=self.options,
                                                exclude_layout=self.record.layout_id)
            except GenerationError as error:
                self.last_error = str(error)
                return False
            result = self.world.restart(game_map=candidate.maze, spawns=candidate.spawns,
                                        allow_active=allow_active)
            if result:
                self.record = candidate
        if result:
            self.last_error = None
        return result
