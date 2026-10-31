"""Bounded seeded grid generation; private host metadata never enters World."""
from dataclasses import dataclass, replace
from random import Random

from tank_game.map import GameMap, Spawn, WallEdge
from tank_game.map_records import layout_digest, snapshot_digest
from tank_game.map_validation import MapValidationError, validate_random_map

VERSION = 'seeded-loops-v1'


def validate_seed(seed):
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError('map seed must be an integer from 0 to 4294967295')


@dataclass(frozen=True)
class GeneratorOptions:
    extra_openings_max: int = 6
    attempt_limit: int = 32

    def __post_init__(self):
        if (type(self.extra_openings_max) is not int or not 0 <= self.extra_openings_max <= 82
                or type(self.attempt_limit) is not int or not 1 <= self.attempt_limit <= 32):
            raise ValueError('extra openings must be 0..82; attempt limit must be 1..32')


@dataclass(frozen=True)
class GeneratedMap:
    maze: GameMap
    spawns: tuple[Spawn, Spawn]
    seed: int
    attempt: int
    generator_version: str
    options: GeneratorOptions
    layout_id: str
    map_id: str
    rejections: tuple[str, ...]


DEFAULT_OPTIONS = GeneratorOptions()


class GenerationError(ValueError):
    def __init__(self, seed, rejections):
        self.seed, self.rejections = seed, tuple(rejections)
        super().__init__(f'map seed {seed}: exhausted {len(rejections)} candidates; '
                         f'{rejections[-1] if rejections else "no candidates"}')


def _neighbors(cell):
    c, r = cell
    return [(x, y) for x, y in ((c-1, r), (c, r-1), (c, r+1), (c+1, r))
            if 0 <= x < 8 and 0 <= y < 6]


def _shared(a, b):
    return (WallEdge('vertical', max(a[0], b[0]), a[1]) if a[1] == b[1]
            else WallEdge('horizontal', a[0], max(a[1], b[1])))


def _sorted(edges):
    return tuple(sorted(edges, key=lambda e: (e.orientation, e.row, e.column)))


def _internal(edge):
    return (0 < edge.row < 6 if edge.orientation == 'horizontal' else 0 < edge.column < 8)


def generate_base(seed: int, attempt: int = 0) -> GameMap:
    validate_seed(seed)
    if type(attempt) is not int or not 0 <= attempt < 32:
        raise ValueError('candidate attempt must be 0..31')
    rng = Random(f'{VERSION}:{seed}:{attempt}:base')
    edges = {WallEdge('horizontal', c, r) for r in range(7) for c in range(8)}
    edges |= {WallEdge('vertical', c, r) for c in range(9) for r in range(6)}
    stack, visited = [(0, 0)], {(0, 0)}
    while stack:
        choices = [n for n in _neighbors(stack[-1]) if n not in visited]
        if not choices:
            stack.pop()
            continue
        neighbor = rng.choice(choices)
        edges.remove(_shared(stack[-1], neighbor))
        visited.add(neighbor)
        stack.append(neighbor)
    return GameMap(8, 6, _sorted(edges))


def remove_dead_ends(maze: GameMap, rng: Random) -> GameMap:
    edges = set(maze.edges)
    for row in range(6):
        for col in range(8):
            cell = col, row
            adjacent = _neighbors(cell)
            if sum(_shared(cell, n) not in edges for n in adjacent) < 2:
                closed = [_shared(cell, n) for n in adjacent if _shared(cell, n) in edges]
                if closed:
                    edges.remove(rng.choice(closed))
    return replace(maze, edges=_sorted(edges))


def select_spawns(maze: GameMap, rng: Random, radius: float) -> tuple[Spawn, Spawn]:
    spawns = (Spawn(16, 16+32*rng.randrange(6), 0),
              Spawn(240, 16+32*rng.randrange(6), 180))
    validate_random_map(replace(maze, spawn=spawns[0]), radius, spawns)
    return spawns


def generate_random_map(seed: int, *, radius: float = 8.0,
                        options: GeneratorOptions = DEFAULT_OPTIONS,
                        exclude_layout: str | None = None) -> GeneratedMap:
    validate_seed(seed)
    if not isinstance(options, GeneratorOptions):
        raise TypeError('expected GeneratorOptions')
    rejections = []
    for attempt in range(options.attempt_limit):
        rng = Random(f'{VERSION}:{seed}:{attempt}')
        maze = remove_dead_ends(generate_base(seed, attempt), rng)
        remaining = [e for e in maze.edges if _internal(e)]
        count = rng.randint(0, min(options.extra_openings_max, len(remaining)))
        removed = set(rng.sample(remaining, count))
        maze = replace(maze, edges=tuple(e for e in maze.edges if e not in removed))
        try:
            spawns = select_spawns(maze, rng, radius)
            maze = replace(maze, spawn=spawns[0])
            layout_id = layout_digest(maze)
            if layout_id == exclude_layout:
                raise MapValidationError('repeat_layout', 'candidate repeats the previous walls')
            return GeneratedMap(maze, spawns, seed, attempt, VERSION, options, layout_id,
                                snapshot_digest(maze, spawns), tuple(rejections))
        except MapValidationError as error:
            rejections.append(str(error))
    raise GenerationError(seed, rejections)
