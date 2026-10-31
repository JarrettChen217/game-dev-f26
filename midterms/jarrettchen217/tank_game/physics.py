"""Continuous circle/wall collision and deterministic, speed-limited sliding.

The circle-expanded rectangle has straight faces and rounded corners. Testing
the expanded AABB alone would incorrectly block travel around wall endpoints.
The earliest entry into any rectangle is entry into their solid union, so
connected wall segments do not create collision surfaces at internal seams.
"""

from dataclasses import dataclass, field
from functools import lru_cache
from math import hypot, sqrt

from tank_game.map import Rect
from tank_game.paths import Segment

CONTACT_GAP = 1e-7  # world units; back off along the swept path before contact
TIME_EPS = 1e-10
DOT_EPS = 1e-10
MAX_CONTACTS = 16  # conservative fallback stops remaining motion, never tunnels


@dataclass(frozen=True)
class MoveResult:
    x: float
    y: float
    exhausted: bool = False
    path: tuple[Segment, ...] = field(default=(), compare=False)


def _contacts(x, y, radius, dx, dy, wall):
    """Yield entering contact fractions and outward unit normals for one wall."""
    left, right = wall.x, wall.x + wall.width
    top, bottom = wall.y, wall.y + wall.height
    # Flat portions of the rounded rectangle (not the whole expanded AABB).
    if dx:
        for face, nx in ((left - radius, -1), (right + radius, 1)):
            t = (face - x) / dx
            if (-TIME_EPS <= t <= 1 + TIME_EPS and dx * nx < -DOT_EPS
                    and top <= y + dy * t <= bottom):
                yield max(0, min(1, t)), (nx, 0)
    if dy:
        for face, ny in ((top - radius, -1), (bottom + radius, 1)):
            t = (face - y) / dy
            if (-TIME_EPS <= t <= 1 + TIME_EPS and dy * ny < -DOT_EPS
                    and left <= x + dx * t <= right):
                yield max(0, min(1, t)), (0, ny)
    a = dx * dx + dy * dy
    for cx, sx in ((left, -1), (right, 1)):
        for cy, sy in ((top, -1), (bottom, 1)):
            px, py = x - cx, y - cy
            b = px * dx + py * dy
            c = px * px + py * py - radius * radius
            discriminant = b * b - a * c
            if discriminant < 0:
                continue
            t = (-b - sqrt(discriminant)) / a
            if not -TIME_EPS <= t <= 1 + TIME_EPS:
                continue
            nx, ny = x + dx * t - cx, y + dy * t - cy
            if nx * sx < -CONTACT_GAP or ny * sy < -CONTACT_GAP:
                continue
            length = hypot(nx, ny)
            if not length:
                continue
            normal = nx / length, ny / length
            if dx * normal[0] + dy * normal[1] < -DOT_EPS:
                yield max(0, min(1, t)), normal


def _slide(dx, dy, normals):
    """Closest displacement satisfying every simultaneous contact half-plane.

    In two dimensions the projection lies inside the cone, on one boundary,
    or at the origin. Selecting among those candidates avoids order-dependent
    sequential projections at a corner and can only reduce displacement speed.
    """
    def legal(vector):
        return all(vector[0] * nx + vector[1] * ny >= -DOT_EPS for nx, ny in normals)

    if legal((dx, dy)):
        return dx, dy
    candidates = [(0.0, 0.0)]
    for nx, ny in normals:
        dot = dx * nx + dy * ny
        vector = dx - dot * nx, dy - dot * ny
        if legal(vector):
            candidates.append(vector)
    return min(candidates, key=lambda v: ((v[0] - dx) ** 2 + (v[1] - dy) ** 2, v))


def move_circle(x: float, y: float, radius: float, dx: float, dy: float,
                walls: tuple[Rect, ...], *, duration: float = 1) -> MoveResult:
    """Sweep and slide; retain each timed leg for dynamic hit detection."""
    path = []
    elapsed, remaining = 0.0, duration
    for _ in range(MAX_CONTACTS):
        distance = hypot(dx, dy)
        if distance <= CONTACT_GAP:
            path.append(Segment(elapsed, duration, x, y, x, y))
            return MoveResult(x, y, path=tuple(path))
        contact = first_wall_contact(x, y, radius, dx, dy, walls)
        if contact is None:
            path.append(Segment(elapsed, duration, x, y, x + dx, y + dy))
            return MoveResult(x + dx, y + dy, path=tuple(path))
        t, normals = contact
        safe_t = max(0, t - CONTACT_GAP / distance)
        nx, ny = x + dx * safe_t, y + dy * safe_t
        end = elapsed + remaining * t
        path.append(Segment(elapsed, end, x, y, nx, ny))
        x, y = nx, ny
        elapsed, remaining = end, remaining * (1 - t)
        dx, dy = _slide(dx * (1 - t), dy * (1 - t), normals)
    path.append(Segment(elapsed, duration, x, y, x, y))
    return MoveResult(x, y, exhausted=hypot(dx, dy) > CONTACT_GAP, path=tuple(path))


def first_wall_contact(x, y, radius, dx, dy, walls):
    """Earliest union entry and deterministic simultaneous surface normals."""
    distance = hypot(dx, dy)
    if not distance:
        return None
    hits = [hit for wall in walls for hit in _contacts(x, y, radius, dx, dy, wall)]
    if not hits:
        return None
    t = min(hit[0] for hit in hits)
    tolerance = CONTACT_GAP / distance
    normals = tuple(sorted({n for time, n in hits if abs(time - t) <= tolerance}))
    return t, normals


def circle_clear(x, y, radius, walls):
    """A complete circle must have positive clearance from every solid wall."""
    return all(hypot(x - max(w.x, min(x, w.x + w.width)),
                     y - max(w.y, min(y, w.y + w.height))) > radius
               for w in walls)


@lru_cache(maxsize=64)
def _joined_walls(walls):
    """Remove internal endpoints of touching/overlapping collinear wall bands.

    Grid-edge walls are one solid union, not separate bumper segments. Merging
    equal bands also avoids nearly simultaneous false endpoint normals near a
    seam. Sorting and a fixed-point pass make the result independent of order.
    """
    result = sorted(set(walls), key=lambda w: (w.x, w.y, w.width, w.height))
    while True:
        merged = False
        for i, a in enumerate(result):
            for j in range(i + 1, len(result)):
                b = result[j]
                if (a.x == b.x and a.width == b.width
                        and max(a.y, b.y) <= min(a.y + a.height, b.y + b.height)):
                    top = min(a.y, b.y)
                    joined = Rect(a.x, top, a.width,
                                  max(a.y + a.height, b.y + b.height) - top)
                elif (a.y == b.y and a.height == b.height
                      and max(a.x, b.x) <= min(a.x + a.width, b.x + b.width)):
                    left = min(a.x, b.x)
                    joined = Rect(left, a.y,
                                  max(a.x + a.width, b.x + b.width) - left, a.height)
                else:
                    continue
                result[i] = joined
                result.pop(j)
                merged = True
                break
            if merged:
                break
        if not merged:
            return tuple(sorted(result, key=lambda w: (w.x, w.y, w.width, w.height)))


@dataclass(frozen=True)
class RicochetResult:
    x: float
    y: float
    vx: float
    vy: float
    contacts: int = 0
    exhausted: bool = False
    path: tuple[Segment, ...] = field(default=(), compare=False)


def ricochet_circle(x, y, radius, vx, vy, dt, walls):
    """Sweep and reflect; preserve speed and retain wall-respecting timed legs."""
    walls = _joined_walls(walls)
    remaining, elapsed = dt, 0.0
    path = []
    for count in range(MAX_CONTACTS):
        dx, dy = vx * remaining, vy * remaining
        distance = hypot(dx, dy)
        if not distance:
            path.append(Segment(elapsed, dt, x, y, x, y))
            return RicochetResult(x, y, vx, vy, count, path=tuple(path))
        contact = first_wall_contact(x, y, radius, dx, dy, walls)
        if contact is None:
            path.append(Segment(elapsed, dt, x, y, x + dx, y + dy))
            return RicochetResult(x + dx, y + dy, vx, vy, count, path=tuple(path))
        t, normals = contact
        safe_t = max(0, t - CONTACT_GAP / distance)
        next_x, next_y = x + dx * safe_t, y + dy * safe_t
        end = elapsed + remaining * t
        path.append(Segment(elapsed, end, x, y, next_x, next_y))
        x, y = next_x, next_y
        nx, ny = normals[0]
        if any(abs(nx * other_y - ny * other_x) > 1e-8
               for other_x, other_y in normals[1:]):
            vx, vy = -vx, -vy
        else:
            dot = vx * nx + vy * ny
            vx, vy = vx - 2 * dot * nx, vy - 2 * dot * ny
        elapsed, remaining = end, remaining * (1 - t)
    path.append(Segment(elapsed, dt, x, y, x, y))
    return RicochetResult(x, y, vx, vy, MAX_CONTACTS,
                          exhausted=remaining > 0, path=tuple(path))
