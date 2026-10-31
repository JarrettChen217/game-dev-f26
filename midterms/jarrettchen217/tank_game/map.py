"""Immutable square-cell maze with walls on cell edges, not solid wall tiles."""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    """An axis-aligned wall rectangle in world coordinates."""

    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class Spawn:
    """Tank center and heading (0 degrees right, 90 degrees down)."""

    x: float
    y: float
    heading_deg: float


@dataclass(frozen=True)
class WallEdge:
    """One cell-length horizontal/vertical edge, identified by its start vertex."""

    orientation: str
    column: int
    row: int


def _finite_number(value: object) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


@dataclass(frozen=True)
class GameMap:
    """Square floor cells separated by optional thin walls.

    Internal walls straddle grid lines; boundary walls lie entirely inside the
    world. Rectangles are the authoritative shared rendering/collision geometry.
    Touching segments form a solid union; future physics must ignore its seams.
    """

    columns: int
    rows: int
    edges: tuple[WallEdge, ...]
    tile_size: int = 32
    wall_thickness: int = 2
    spawn: Spawn = Spawn(16, 16, 0)

    @property
    def width(self) -> int:
        return self.columns * self.tile_size

    @property
    def height(self) -> int:
        return self.rows * self.tile_size

    @property
    def walls(self) -> tuple[Rect, ...]:
        half = self.wall_thickness / 2
        walls = []
        for edge in self.edges:
            if edge.orientation == 'horizontal':
                y = max(0, min(edge.row * self.tile_size - half,
                               self.height - self.wall_thickness))
                walls.append(Rect(edge.column * self.tile_size, y,
                                  self.tile_size, self.wall_thickness))
            else:
                x = max(0, min(edge.column * self.tile_size - half,
                               self.width - self.wall_thickness))
                walls.append(Rect(x, edge.row * self.tile_size,
                                  self.wall_thickness, self.tile_size))
        return tuple(walls)

    def _validate_structure(self) -> None:
        for name in ('columns', 'rows', 'tile_size', 'wall_thickness'):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f'{name} must be a positive integer')
        if self.wall_thickness >= self.tile_size:
            raise ValueError('walls must be thinner than a floor cell')
        if not _finite_number(self.width) or not _finite_number(self.height):
            raise ValueError('map dimensions must be finite')
        if type(self.edges) is not tuple:
            raise ValueError('edges must be an immutable tuple')
        seen = set()
        for edge in self.edges:
            if (type(edge) is not WallEdge or type(edge.orientation) is not str
                    or edge.orientation not in ('horizontal', 'vertical')
                    or type(edge.column) is not int or type(edge.row) is not int):
                raise ValueError('each edge must have a valid orientation and integer vertex')
            max_column = self.columns - (edge.orientation == 'horizontal')
            max_row = self.rows - (edge.orientation == 'vertical')
            if not (0 <= edge.column <= max_column and 0 <= edge.row <= max_row):
                raise ValueError('edge must lie on the map grid')
            if edge in seen:
                raise ValueError('duplicate wall edge')
            seen.add(edge)
        boundary = {WallEdge('horizontal', x, y) for y in (0, self.rows)
                    for x in range(self.columns)}
        boundary.update(WallEdge('vertical', x, y) for x in (0, self.columns)
                        for y in range(self.rows))
        if not boundary.issubset(seen):
            raise ValueError('all outer grid edges must have walls')
        if type(self.spawn) is not Spawn or any(not _finite_number(value) for value in
                                               (self.spawn.x, self.spawn.y,
                                                self.spawn.heading_deg)):
            raise ValueError('spawn must contain finite numeric coordinates and heading')

    def is_legal_spawn(self, radius: float) -> bool:
        """Require positive circle clearance, including wall endpoints and corners."""
        try:
            self._validate_structure()
        except ValueError:
            return False
        if not _finite_number(radius) or radius <= 0:
            return False
        x, y = self.spawn.x, self.spawn.y
        if not (radius < x < self.width - radius and
                radius < y < self.height - radius):
            return False
        for wall in self.walls:
            nearest_x = max(wall.x, min(x, wall.x + wall.width))
            nearest_y = max(wall.y, min(y, wall.y + wall.height))
            if math.hypot(x - nearest_x, y - nearest_y) <= radius:
                return False
        return True

    def validate(self, radius: float) -> None:
        self._validate_structure()
        if not _finite_number(radius) or radius <= 0:
            raise ValueError('spawn radius must be a positive finite number')
        if not self.is_legal_spawn(radius):
            raise ValueError('spawn circle must be inside the map with clearance from walls')


def fixed_map() -> GameMap:
    """Original deterministic 8 × 6 layout; every cell is a 32-unit square."""
    columns, rows = 8, 6
    edges = [WallEdge('horizontal', x, y) for y in (0, rows) for x in range(columns)]
    edges += [WallEdge('vertical', x, y) for x in (0, columns) for y in range(rows)]
    edges += [WallEdge('vertical', x, y) for x, span in ((2, range(4)),
              (4, range(2, 6)), (6, range(4))) for y in span]
    edges += [WallEdge('horizontal', x, y) for x, y in
              ((0, 2), (3, 1), (2, 4), (4, 4), (6, 2))]
    return GameMap(columns, rows, tuple(edges))
