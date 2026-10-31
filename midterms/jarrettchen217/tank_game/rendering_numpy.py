"""Optional array acceleration of the existing 4x4 tank art, with identical samples.

The research Hybrid runtime already uses NumPy. Default product rendering keeps
its dependency-free rasterizer; this module is loaded only for the opt-in view.
"""
from functools import lru_cache
from math import cos, floor, radians, sin

import numpy as np

from tank_game.rendering import AA_SAMPLES, SAMPLE_COLORS


@lru_cache(maxsize=128)
def array_tank_coverage(radius: float, heading: float, phase_x: float, phase_y: float) -> tuple:
    c, s = cos(radians(heading)), sin(radians(heading))
    half_stroke = .4 / radius
    left, right = floor(phase_x-radius-1), floor(phase_x+radius+1)
    top, bottom = floor(phase_y-radius-1), floor(phase_y+radius+1)
    offsets = (np.arange(AA_SAMPLES, dtype=np.float64) + .5) / AA_SAMPLES
    xs = ((np.arange(left, right+1)[:, None] + offsets - phase_x) / radius).ravel()
    ys = ((np.arange(top, bottom+1)[:, None] + offsets - phase_y) / radius).ravel()
    nx, ny = np.meshgrid(xs, ys)
    u, v = nx*c + ny*s, -nx*s + ny*c
    colors = np.full(nx.shape, -1, dtype=np.int8)
    for x0, y0, x1, y1, fill in ((-.62, -.66, .62, -.43, 5),
                                (-.62, .43, .62, .66, 5),
                                (-.58, -.43, .58, .43, 11),
                                (.12, -.1, .96, .1, 3)):
        colors[(x0-half_stroke <= u) & (u <= x1+half_stroke)
               & (y0-half_stroke <= v) & (v <= y1+half_stroke)] = 0
        colors[(x0+half_stroke < u) & (u < x1-half_stroke)
               & (y0+half_stroke < v) & (v < y1-half_stroke)] = fill
    distance = nx*nx + ny*ny
    outer = (.36+half_stroke)**2
    inner = (.36-half_stroke)**2
    colors[distance <= outer] = 0
    colors[(distance <= outer) & (distance < inner)] = 3
    colors[(nx+.08)**2 + (ny+.08)**2 <= .15**2] = 11
    samples = colors.reshape(bottom-top+1, AA_SAMPLES, right-left+1, AA_SAMPLES)
    counts = np.stack([(samples == color).sum(axis=(1, 3)) for color in SAMPLE_COLORS], axis=-1)
    rows, columns = np.nonzero(counts.sum(axis=-1))
    return tuple((int(x+left), int(y+top), tuple(map(int, counts[y, x])))
                 for y, x in zip(rows, columns, strict=True))
