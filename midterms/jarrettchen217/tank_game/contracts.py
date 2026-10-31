"""Explicit rule compatibility and resolved episode identities; no host metadata."""
import hashlib
import json
from dataclasses import asdict, dataclass

from tank_game.episodes import EpisodeSpec, create_world
from tank_game.map_records import encode_map


@dataclass(frozen=True)
class RunContract:
    rules_version: str
    action_schema_version: int
    public_observation_schema_version: int
    physics_hz: int
    decision_hz: int
    episode_digest: str


def make_run_contract(spec: EpisodeSpec, *, decision_hz=10) -> RunContract:
    if type(decision_hz) is not int or decision_hz <= 0 or spec.config.tick_rate % decision_hz:
        raise ValueError('positive integer decision_hz must divide physics_hz')
    world = create_world(spec)  # One authoritative validation/default-spawn resolver.
    payload = {'map': encode_map(spec.game_map), 'config': asdict(spec.config),
               'duel': spec.duel, 'spawns': [asdict(s) for s in world._spawns],
               'round_limit': spec.round_limit}
    if spec.collision_profile!='circle':
        payload['collision_profile']=world.observe('tank-1')['collision_profile']
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return RunContract('tank-rules-v1' if spec.collision_profile=='circle' else 'tank-rectangle-v1', 1, world.observe('tank-1')['schema_version'], spec.config.tick_rate,
                       decision_hz, hashlib.sha256(encoded.encode()).hexdigest())
