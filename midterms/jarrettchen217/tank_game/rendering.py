"""Original geometric tank art. No reference sprites or simulation access."""

from functools import lru_cache
from math import cos, floor, radians, sin

BASE_PALETTE = (0x182126, 0x23323A, 0x7E2553, 0x1A6D57,
                0xAB5236, 0x606563, 0xE3E4DE, 0xF4F4EE,
                0xFF004D, 0xFFA300, 0xF5C857, 0x52B788,
                0x29ADFF, 0xD4D6CF, 0xFF77A8, 0xFFCCAA)
SAMPLE_COLORS = (0, 3, 5, 11)
AA_SAMPLES = 4


def _rgb(color):
    return (color >> 16) & 255, (color >> 8) & 255, color & 255


def _blend_palette():
    """Fixed shades keep UI colors stable and stay within Pyxel's 256 slots."""
    colors = list(BASE_PALETTE)
    used = set(colors)
    indices = (0, 3, 5, 6, 11, 13)
    for i, first in enumerate(indices):
        for second in indices[i + 1:]:
            a, b = _rgb(BASE_PALETTE[first]), _rgb(BASE_PALETTE[second])
            for weight in range(1, 16):
                r, g, blue = (round((x * weight + y * (16 - weight)) / 16)
                              for x, y in zip(a, b, strict=True))
                color = (r << 16) | (g << 8) | blue
                if color not in used:
                    colors.append(color)
                    used.add(color)
    return tuple(colors)


PALETTE = _blend_palette()
RGB_PALETTE = tuple(map(_rgb, PALETTE))
_EXACT_COLORS = {rgb: index for index, rgb in enumerate(RGB_PALETTE)}


@lru_cache(maxsize=4096)
def _nearest_color(rgb):
    if rgb in _EXACT_COLORS:
        return _EXACT_COLORS[rgb]
    return min(range(len(PALETTE)), key=lambda index:
               sum((a - b) ** 2 for a, b in zip(rgb, RGB_PALETTE[index], strict=True)))


def tank_polygons(x: float, y: float, radius: float, heading_deg: float) -> dict:
    """Rotate the entire silhouette within the existing circular body boundary."""
    angle = radians(heading_deg)
    c, s = cos(angle), sin(angle)

    def rectangle(left, top, right, bottom):
        return tuple((x + radius * (px * c - py * s),
                      y + radius * (px * s + py * c))
                     for px, py in ((left, top), (right, top),
                                    (right, bottom), (left, bottom)))

    return {
        'left_track': rectangle(-.62, -.66, .62, -.43),
        'right_track': rectangle(-.62, .43, .62, .66),
        'body': rectangle(-.58, -.43, .58, .43),
        'barrel': rectangle(.12, -.1, .96, .1),
    }


@lru_cache(maxsize=128)
def tank_coverage(radius: float, heading: float, phase_x: float, phase_y: float) -> tuple:
    """4x4 subpixel coverage, relative to the floored screen center.

    Fractions affect coverage instead of snapping an entire silhouette. Bounded
    caches reuse recurring poses without storing world state or inventing motion.
    Returned counts correspond to SAMPLE_COLORS; missing samples are transparent.
    """
    c, s = cos(radians(heading)), sin(radians(heading))
    half_stroke = .4 / radius
    shapes = ((-.62, -.66, .62, -.43, 5), (-.62, .43, .62, .66, 5),
              (-.58, -.43, .58, .43, 11), (.12, -.1, .96, .1, 3))
    inner_turret, outer_turret = (.36 - half_stroke) ** 2, (.36 + half_stroke) ** 2
    offsets = tuple((i + .5) / AA_SAMPLES for i in range(AA_SAMPLES))
    pixels = []
    for py in range(floor(phase_y - radius - 1), floor(phase_y + radius + 1) + 1):
        for px in range(floor(phase_x - radius - 1), floor(phase_x + radius + 1) + 1):
            counts = [0, 0, 0, 0]
            for sy in offsets:
                ny = (py + sy - phase_y) / radius
                for sx in offsets:
                    nx = (px + sx - phase_x) / radius
                    u, v = nx * c + ny * s, -nx * s + ny * c
                    color = None
                    for left, top, right, bottom, fill in shapes:
                        if (left - half_stroke <= u <= right + half_stroke
                                and top - half_stroke <= v <= bottom + half_stroke):
                            color = (fill if left + half_stroke < u < right - half_stroke
                                     and top + half_stroke < v < bottom - half_stroke else 0)
                    distance = nx * nx + ny * ny
                    if distance <= outer_turret:
                        color = 3 if distance < inner_turret else 0
                    if (nx + .08) ** 2 + (ny + .08) ** 2 <= .15 ** 2:
                        color = 11
                    if color is not None:
                        counts[SAMPLE_COLORS.index(color)] += 1
            if sum(counts):
                pixels.append((px, py, tuple(counts)))
    return tuple(pixels)


class SmoothTankRenderer:
    """Blend original tank coverage over the actual already-drawn board pixels."""

    def __init__(self, *, coverage=tank_coverage):
        self.coverage = coverage

    def draw(self, pyxel, tank: tuple, *, origin: tuple[int, int], scale: int) -> None:
        x, y, radius, heading = tank
        x, y = origin[0] + x * scale, origin[1] + y * scale
        base_x, base_y = floor(x), floor(y)
        total = AA_SAMPLES ** 2
        for px, py, counts in self.coverage(radius * scale, heading,
                                            x - base_x, y - base_y):
            background = RGB_PALETTE[pyxel.pget(base_x + px, base_y + py)]
            empty = total - sum(counts)
            rgb = tuple(round((background[channel] * empty
                               + sum(RGB_PALETTE[color][channel] * count
                                     for color, count in zip(SAMPLE_COLORS, counts, strict=True)))
                              / total) for channel in range(3))
            pyxel.pset(base_x + px, base_y + py, _nearest_color(rgb))
