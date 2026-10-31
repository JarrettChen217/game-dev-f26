"""Optional source-aligned Killfield rules, used by one Tank World only.

Adapted from Cichlider/killfield game.rs/constants.rs/maze.rs (MIT, copyright
2026 Cichlider). Full notice: research/killfield/tank_transfer/LICENSE.killfield.
This module contains pure geometry/rule functions, no independent game state.
"""

from dataclasses import replace
from functools import lru_cache
from math import cos, floor, hypot, radians, sin, sqrt

from tank_game.config import GameConfig
from tank_game.entities import BulletState
from tank_game.map import Rect, fixed_map

RULES_PROFILE = "killfield-rules-v2"
FRONT = (
    (-30.5, -40.5),
    (-15.25, -40.5),
    (15.25, -40.5),
    (30.5, -40.5),
    (-7.5, -53.28125),
    (7.5, -53.28125),
)
REAR = ((-30.5, 40.5), (-15.25, 40.5), (0, 40.5), (15.25, 40.5), (30.5, 40.5))
RIGHT = tuple((30.5, y) for y in (-27, -13.5, 0, 13.5, 27))
LEFT = tuple((-30.5, y) for y in (-27, -13.5, 0, 13.5, 27))
PROBES = FRONT + REAR + RIGHT + LEFT


def rules_episode(game_map=None, *, duel=True, spawns=None, round_limit=120):
    from tank_game.episodes import EpisodeSpec

    maze = game_map or fixed_map()
    size = maze.tile_size
    maze = replace(maze, wall_thickness=2 * floor(size / 16))
    config = replace(
        GameConfig(),
        tick_rate=25,
        forward_speed=2 * size,
        reverse_speed=1.25 * size,
        turn_speed_deg=250,
        bullet_speed=2.25 * size,
        fire_interval=1 / 25,
        bullet_radius=3.5 * 0.0055 * size,
    )
    return EpisodeSpec(
        maze,
        config,
        duel=duel,
        spawns=spawns,
        round_limit=round_limit,
        research_profile=RULES_PROFILE,
    )


def author_walls(maze):
    """Author wall strokes expand endpoints as well as their normal by floor(S/16)."""
    size = maze.tile_size
    half = floor(size / 16)
    out = []
    for e in maze.edges:
        x, y = e.column * size, e.row * size
        width, height = (size, 0) if e.orientation == "horizontal" else (0, size)
        out.append(Rect(x - half, y - half, width + 2 * half, height + 2 * half))
    return tuple(out)


class WallIndex:
    """Exact point-query broad phase; original rectangles/inequalities unchanged."""
    def __init__(self, rectangles, cell_size):
        self.rectangles = tuple(rectangles)
        self.cell_size = cell_size
        self.cells = {}
        for rect in self.rectangles:
            for x in range(floor(rect.x/cell_size), floor((rect.x+rect.width)/cell_size)+1):
                for y in range(floor(rect.y/cell_size), floor((rect.y+rect.height)/cell_size)+1):
                    self.cells.setdefault((x,y), []).append(rect)
        self._bounds = {cell: tuple((r.x, r.y, r.x+r.width, r.y+r.height) for r in candidates)
                        for cell, candidates in self.cells.items()}

    def __iter__(self):
        return iter(self.rectangles)

    def at(self, x, y):
        return self.cells.get((floor(x/self.cell_size), floor(y/self.cell_size)), ())

    def hit(self, x, y):
        for left, top, right, bottom in self._bounds.get(
                (floor(x/self.cell_size), floor(y/self.cell_size)), ()):
            if left <= x <= right and top <= y <= bottom:
                return True
        return False


def wall_hit(x, y, walls):
    if isinstance(walls, WallIndex):
        return walls.hit(x, y)
    for wall in walls:
        if wall.x <= x <= wall.x + wall.width and wall.y <= y <= wall.y + wall.height:
            return True
    return False


def to_global(tank, lx, ly, scale):
    a = radians(tank.heading_deg + 90)
    c, s = cos(a), sin(a)
    factor = 0.0055 * scale
    return tank.x + factor * (lx * c - ly * s), tank.y + factor * (lx * s + ly * c)


def hull_polygons(tank, scale):
    return tuple(
        tuple(to_global(tank, x, y, scale) for x, y in points)
        for points in (
            ((-30.5, -40.5), (30.5, -40.5), (30.5, 40.5), (-30.5, 40.5)),
            ((-8.5, -55), (8.5, -55), (8.5, 0), (-8.5, 0)),
        )
    )


def point_in_tank(tank, x, y, scale):
    a = radians(tank.heading_deg + 90)
    c, s = cos(a), sin(a)
    factor = 0.0055 * scale
    dx, dy = x - tank.x, y - tank.y
    lx = (dx * c + dy * s) / factor
    ly = (-dx * s + dy * c) / factor
    return (-30.5 <= lx <= 30.5 and -40.5 <= ly <= 40.5) or (abs(lx) <= 8.5 and -55 <= ly <= 0)


@lru_cache(maxsize=256)
def _probe_offsets(heading, scale, points):
    """Pose-independent part of the original to_global formula, without rounding."""
    angle = radians(heading + 90)
    c, s = cos(angle), sin(angle)
    factor = .0055 * scale
    return tuple((factor * (x*c-y*s), factor * (x*s+y*c)) for x, y in points)


def probes_hit(tank, walls, scale, points=PROBES):
    for dx, dy in _probe_offsets(tank.heading_deg, scale, tuple(points)):
        if wall_hit(tank.x+dx, tank.y+dy, walls):
            return True
    return False


def _separate(tank, walls, scale):
    if not probes_hit(tank, walls, scale):
        return tank
    d = 1 / sqrt(2)
    for ring in range(1, 6):
        distance = scale / 50 * ring / 5
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (d, d), (d, -d), (-d, d), (-d, -d)):
            candidate = replace(tank, x=tank.x + dx * distance, y=tank.y + dy * distance)
            if not probes_hit(candidate, walls, scale):
                return candidate
    return None


def _slide(tank, walls, scale, dx, dy):
    epsilon = max(1e-9, scale * 1e-9)
    xb = abs(dx) > epsilon and probes_hit(replace(tank, x=tank.x + dx), walls, scale)
    yb = abs(dy) > epsilon and probes_hit(replace(tank, y=tank.y + dy), walls, scale)
    if xb == yb:
        return tank, 0
    tx, ty = (0 if xb else dx), (0 if yb else dy)
    if hypot(tx, ty) <= epsilon or hypot(dx, dy) <= epsilon:
        return tank, 0
    incidence = (abs(dx) if xb else abs(dy)) / hypot(dx, dy)
    retention = max(0.70, min(0.96, 1 - 0.30 * incidence))
    return replace(tank, x=tank.x + tx * retention, y=tank.y + ty * retention), 2 if xb else 1


def _align(tank, walls, scale, axis):
    first = 0 if axis == 1 else 270
    deltas = [(target - tank.heading_deg + 180) % 360 - 180 for target in (first, first + 180)]
    delta = min(deltas, key=abs)
    turn = max(-2, min(2, delta))
    candidate = replace(tank, heading_deg=tank.heading_deg + turn)
    return tank if probes_hit(candidate, walls, scale) else candidate


def move_tank(tank, action, walls, scale):
    """Five discrete source substeps, wall probes, contact drag and tangent torque."""
    if action.throttle or action.turn:
        tank = _separate(tank, walls, scale) or tank
    old = tank
    move = (2 * scale if action.throttle > 0 else 1.25 * scale) * action.throttle / 25 / 5
    turn = action.turn * 2
    hit = False
    sliding = False
    tangent = 0

    # Preserve all five normalization/addition steps in source order. Intermediate
    # records cannot be observed on this collision-free proposal; validate only
    # the completed proposal, then use the unchanged collision fallback if needed.
    x, y, heading = tank.x, tank.y, tank.heading_deg
    for _ in range(5):
        heading = ((heading + turn) % 360) % 360
        a = radians(heading)
        x, y = x + cos(a) * move, y + sin(a) * move
    tank = replace(tank, heading_deg=heading, x=x, y=y)
    if probes_hit(tank, walls, scale):
        tank = old
        for _ in range(5):
            prior = tank
            tank = replace(tank, heading_deg=tank.heading_deg + turn)
            if probes_hit(tank, walls, scale):
                separated = _separate(tank, walls, scale)
                if separated is None:
                    tank = prior
                    hit = True
                else:
                    tank = separated
                    sliding = True
            prior = tank
            a = radians(tank.heading_deg)
            dx, dy = cos(a) * move, sin(a) * move
            tank = replace(tank, x=tank.x + dx, y=tank.y + dy)
            leading = FRONT if move > 0 else REAR if move < 0 else ()
            if leading and probes_hit(tank, walls, scale, leading):
                tank, axis = _slide(prior, walls, scale, dx, dy)
                if axis:
                    sliding = True
                    tangent = axis
                else:
                    hit = True
        if tangent:
            tank = _align(tank, walls, scale, tangent)
    offset = tank.heading_deg % 10
    if not hit and turn and offset:
        tank = replace(tank, heading_deg=tank.heading_deg - offset + (10 if offset >= 5 else 0))
    return tank, {"hit_something": hit, "wall_sliding": sliding}


def advance_bullet(bullet, walls, hz):
    """Seven point substeps and author's asymmetric reflection probes; no sweep."""
    x, y = bullet.x, bullet.y
    dx, dy = bullet.vx / hz / 7, bullet.vy / hz / 7
    bounces = 0
    for _ in range(7):
        px, py = x, y
        x += dx
        y += dy
        if wall_hit(x, y, walls):
            bounces += 1
            hx = wall_hit(px - dx, py + dy, walls)
            hy = wall_hit(px + dx, py - dy, walls)
            if hx and not hy:
                dy = -dy
            elif hy and not hx:
                dx = -dx
            else:
                dx, dy = -dx, -dy
            x, y = px + dx, py + dy
    # Same validated record/fields; avoid generic dataclass field traversal for
    # every frame of all forecasted trajectories.
    return BulletState(bullet.id, x, y, dx * hz * 7, dy * hz * 7,
                       radius=bullet.radius, owner_id=bullet.owner_id,
                       age=bullet.age + 1 / hz), bounces
