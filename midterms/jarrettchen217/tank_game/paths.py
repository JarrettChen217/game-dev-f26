"""Timed piecewise paths for continuous moving-circle contact, without rendering."""

from dataclasses import dataclass
from math import sqrt


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    x0: float
    y0: float
    x1: float
    y1: float

    def at(self, time: float) -> tuple[float, float]:
        fraction = ((time - self.start) / (self.end - self.start)
                    if self.end > self.start else 0)
        fraction = max(0, min(1, fraction))
        return (self.x0 + (self.x1 - self.x0) * fraction,
                self.y0 + (self.y1 - self.y0) * fraction)


def position(path: tuple[Segment, ...], time: float) -> tuple[float, float]:
    for segment in path:
        if time <= segment.end:
            return segment.at(time)
    return path[-1].at(time)


def first_hit(first: tuple[Segment, ...], second: tuple[Segment, ...],
              radius: float) -> float | None:
    """Earliest inclusive circle contact on overlapping segment time intervals.

    Paths already obey walls. Relative motion is solved per interval, never
    along a chord joining endpoints across a bounce or a sliding corner.
    """
    earliest = None
    for a in first:
        for b in second:
            start, end = max(a.start, b.start), min(a.end, b.end)
            if end < start:
                continue
            ax, ay = a.at(start)
            bx, by = b.at(start)
            px, py = ax - bx, ay - by
            c = px * px + py * py - radius * radius
            if c <= 0:
                hit = start
            elif end == start:
                continue
            else:
                ex, ey = a.at(end)
                fx, fy = b.at(end)
                dx, dy = ex - fx - px, ey - fy - py
                speed2 = dx * dx + dy * dy
                dot = px * dx + py * dy
                discriminant = dot * dot - speed2 * c
                if speed2 == 0 or dot >= 0 or discriminant < 0:
                    continue
                # Stable entry root avoids cancellation for near-touching circles.
                fraction = c / (-dot + sqrt(discriminant))
                if not 0 <= fraction <= 1:
                    continue
                hit = start + fraction * (end - start)
            earliest = hit if earliest is None else min(earliest, hit)
    return earliest
