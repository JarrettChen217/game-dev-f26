"""Host-only reproducibility and geometry research, without playing policies."""
import argparse
import json
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

from tank_game.evaluation import revision
from tank_game.map_records import encode_map
from tank_game.map_validation import validate_random_map
from tank_game.random_maps import DEFAULT_OPTIONS, VERSION, GenerationError, generate_random_map


def run_batch(seeds, *, options=DEFAULT_OPTIONS, output=None):
    output = Path(output) if output is not None else None
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            with output.open('x'):
                pass
        except FileExistsError as error:
            raise ValueError(f'will not overwrite batch evidence: {output}') from error
    report = {'revision': revision(), 'generator_version': VERSION, 'options': asdict(options),
              'radius': 8.0, 'attempted': 0, 'accepted': 0, 'failed': 0,
              'unique_layouts': 0, 'reproducibility_failures': 0, 'maps': []}
    layouts = set()
    for seed in seeds:
        report['attempted'] += 1
        row = {'seed': seed}
        start = perf_counter()
        try:
            record = generate_random_map(seed, options=options)
            seconds = perf_counter()-start
            repeated = generate_random_map(seed, options=options)
            validation = validate_random_map(record.maze, 8, record.spawns)
            reproducible = repeated == record
            report['reproducibility_failures'] += not reproducible
            row.update(map=encode_map(record.maze), spawns=[asdict(s) for s in record.spawns],
                       map_id=record.map_id, layout_id=record.layout_id, attempt=record.attempt,
                       rejections=record.rejections, reproducible=reproducible,
                       internal_walls=len(record.maze.edges)-28,
                       degrees=validation.degrees, spawn_path_edges=len(validation.spawn_path)-1,
                       generation_seconds=seconds)
            report['accepted'] += 1
            layouts.add(record.layout_id)
        except GenerationError as error:
            row.update(error=str(error), rejections=error.rejections)
            report['failed'] += 1
        report['maps'].append(row)
        report['unique_layouts'] = len(layouts)
        if output is not None and (report['attempted'] % 25 == 0 or 'error' in row):
            output.write_text(json.dumps(report, indent=2)+'\n')
    if output is not None:
        output.write_text(json.dumps(report, indent=2)+'\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', type=int, default=0)
    parser.add_argument('--count', type=int, default=1000)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.count <= 0 or args.start < 0 or args.start+args.count > 2**32:
        parser.error('seed range must contain positive count within UINT32')
    try:
        report = run_batch(range(args.start, args.start+args.count), output=args.output)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(json.dumps({k: v for k, v in report.items() if k != 'maps'}, indent=2))
    if report['failed'] or report['reproducibility_failures']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
