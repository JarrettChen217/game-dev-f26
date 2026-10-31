"""Host-only map snapshots and content identities, independent of generation."""
import hashlib
import json
from dataclasses import asdict

from tank_game.map import GameMap, Spawn, WallEdge


def encode_map(maze: GameMap) -> dict:
    return asdict(maze)


def decode_map(raw: dict) -> GameMap:
    try:
        if type(raw) is not dict or set(raw) != {
                'columns', 'rows', 'edges', 'tile_size', 'wall_thickness', 'spawn'}:
            raise ValueError('expected complete map snapshot')
        if type(raw['edges']) not in (list, tuple) or type(raw['spawn']) is not dict:
            raise ValueError('invalid snapshot containers')
        maze = GameMap(raw['columns'], raw['rows'], tuple(WallEdge(**e) for e in raw['edges']),
                       raw['tile_size'], raw['wall_thickness'], Spawn(**raw['spawn']))
        maze._validate_structure()
        return maze
    except (TypeError, KeyError, OverflowError) as error:
        raise ValueError('invalid map snapshot') from error


def _digest(raw):
    payload = json.dumps(raw, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _layout(maze):
    raw = encode_map(maze)
    raw.pop('spawn')
    raw['edges'] = sorted(raw['edges'], key=lambda e: (e['orientation'], e['row'], e['column']))
    return raw


def layout_digest(maze: GameMap) -> str:
    return _digest(_layout(maze))


def snapshot_digest(maze: GameMap, spawns: tuple[Spawn, Spawn]) -> str:
    return _digest({'map': _layout(maze), 'spawns': [asdict(s) for s in spawns]})
