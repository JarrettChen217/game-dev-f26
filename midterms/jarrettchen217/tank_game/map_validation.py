"""Independent final-geometry validation for the optional random-map profile."""
from dataclasses import asdict, dataclass

from tank_game.duel import legal_spawns
from tank_game.map import GameMap, Spawn
from tank_game.navigation import bfs, map_graph


class MapValidationError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(f'{code}: {message}')


@dataclass(frozen=True)
class MapValidation:
    nodes: int
    links: int
    degrees: tuple[int, ...]
    spawn_path: tuple[tuple[int, int], ...]


def validate_random_map(maze: GameMap, radius: float,
                        spawns: tuple[Spawn, Spawn] | None = None) -> MapValidation:
    try:
        if not isinstance(maze, GameMap):
            raise TypeError('expected GameMap')
        maze.validate(radius)
        if (maze.columns, maze.rows, maze.tile_size, maze.wall_thickness) != (8, 6, 32, 2):
            raise ValueError('random maps require 8x6 / 32-unit cells / 2-unit walls')
    except (ValueError, TypeError) as error:
        raise MapValidationError('structure', str(error)) from error
    public = {'walls': [asdict(w) for w in maze.walls], 'columns': maze.columns,
              'rows': maze.rows, 'tile_size': maze.tile_size}
    nodes, graph = map_graph(public, radius)
    if len(nodes) != 48:
        raise MapValidationError('clearance', 'not all 48 floor centers fit the tank')
    pending, reached = [(0, 0)], {(0, 0)}
    while pending:
        for neighbor in graph[pending.pop()]:
            if neighbor not in reached:
                reached.add(neighbor)
                pending.append(neighbor)
    if len(reached) != 48:
        raise MapValidationError('disconnected', f'isolated cells: {sorted(set(nodes)-reached)}')
    dead = sorted(key for key in graph if len(graph[key]) < 2)
    if dead:
        raise MapValidationError('dead_end', f'single-exit cells: {dead}')
    path = ()
    if spawns is not None:
        try:
            legal_spawns(maze, radius, spawns)
            a, b = spawns
            if (a.x != 16 or b.x != 240 or a.heading_deg != 0 or b.heading_deg != 180
                    or any(s.y not in range(16, 192, 32) for s in spawns)):
                raise ValueError('spawns must face inward at left/right column centers')
            path = bfs(graph, (0, int((a.y-16)/32)), (7, int((b.y-16)/32)))
        except (ValueError, TypeError) as error:
            raise MapValidationError('spawns', str(error)) from error
    degrees = tuple(len(graph[key]) for key in sorted(graph))
    return MapValidation(len(nodes), sum(degrees)//2, degrees, path)
