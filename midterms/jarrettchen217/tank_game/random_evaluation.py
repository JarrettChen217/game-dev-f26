"""Predeclare generated-map snapshots before comparing unchanged policies."""
import argparse
import json
from dataclasses import asdict
from pathlib import Path

from tank_game.config import GameConfig
from tank_game.evaluation import DECISION_HZ, TIME_BUDGET, validate_manifest
from tank_game.map_records import encode_map
from tank_game.random_maps import generate_random_map
from tank_game.strategies import POLICIES


def make_random_manifest(seeds, *, round_limit=120):
    conditions = []
    for index, seed in enumerate(seeds):
        record = generate_random_map(seed)
        conditions.append({'id': f'r{index+1:03d}', 'seed': seed, 'map': encode_map(record.maze),
                           'spawns': [asdict(s) for s in record.spawns],
                           'map_id': record.map_id, 'layout_id': record.layout_id,
                           'generation': {'seed': seed, 'attempt': record.attempt,
                                          'generator_version': record.generator_version,
                                          'options': asdict(record.options),
                                          'rejections': list(record.rejections)}})
    manifest = {'schema_version': 2, 'rules': asdict(GameConfig()), 'round_limit': round_limit,
                'decision_hz': DECISION_HZ, 'timeout': TIME_BUDGET,
                'strategies': ['hard', 'simple'],
                'strategy_versions': {name: cls.version for name, cls in POLICIES.items()},
                'conditions': conditions,
                'seed_role': 'host-owned generation; actual map snapshots are replay authority',
                'ai_use_disclosure': 'Codex predeclared generated layouts under Hao direction; '
                                     'outcomes do not determine seed selection.'}
    validate_manifest(manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write-manifest', action='store_true', required=True)
    parser.add_argument('--start', type=int, default=1000)
    parser.add_argument('--count', type=int, default=30)
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    if args.count <= 0 or args.start < 0 or args.start+args.count > 2**32:
        parser.error('seed range must be within UINT32 with positive count')
    if args.manifest.exists():
        parser.error('manifest already exists; will not overwrite frozen conditions')
    manifest = make_random_manifest(range(args.start, args.start+args.count))
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    with args.manifest.open('x') as stream:
        stream.write(json.dumps(manifest, indent=2)+'\n')


if __name__ == '__main__':
    main()
