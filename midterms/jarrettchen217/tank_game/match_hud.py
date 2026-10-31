"""Small portable host HUD: no engine, model, clock or native-window imports.

An adapter supplies actual engine facts. Text/rect primitives are backend-neutral;
coordinates are logical pixels, colors use the existing Tank palette.
"""
from dataclasses import dataclass
from math import ceil

# Shared footer typography/spacing; all offsets are logical pixels from score y.
SCORE_FONT_SCALE = 2
SETTLEMENT_BAR_OFFSET = 16
SETTLEMENT_TEXT_GAP = 6


@dataclass(frozen=True)
class MatchFacts:
    round_id: int | str
    phase: str  # playing, settling, finished
    alive_ids: tuple[str, ...] = ()
    remaining_seconds: float = 0
    total_seconds: float = 0
    winner_id: str | None = None  # finished + None means draw


class SessionScore:
    """Memory-only continuous-session totals; explicit terminal facts count once."""
    def __init__(self, seats):
        self.seats = tuple(seats)
        self.clear()

    def clear(self):
        self.points = dict.fromkeys(self.seats, 0)
        self._finished = set()

    def record(self, facts):
        if facts.phase != 'finished' or facts.round_id in self._finished:
            return
        self._finished.add(facts.round_id)
        if facts.winner_id in self.points:
            self.points[facts.winner_id] += 1


def score_primitives(seats, points, bounds, *, scale=1):
    """seats is ((stable_id, display_name), ...), ordered left then right."""
    x, y, width, _height = bounds
    (left, left_name), (right, right_name) = seats
    middle = f" {points[left]} : {points[right]} "
    char_width = 4*scale
    name_limit = max(1, (width//char_width - len(middle))//2)
    text = left_name[:name_limit] + middle + right_name[:name_limit]
    return (('text', x+(width-len(text)*char_width)//2, y, text, 0),)


def settlement_primitives(seats, facts, bounds, *, text_gap=8):
    """Progress is supplied engine time, never an inferred or wall-clock timer."""
    if facts.phase != 'settling' or facts.total_seconds <= 0:
        return ()
    x, y, width, _height = bounds
    remaining = max(0, facts.remaining_seconds)
    fraction = max(0, min(1, 1-remaining/facts.total_seconds))
    filled = round((width-2)*fraction)
    seconds = ceil(remaining*10-1e-9)/10  # positive remaining never displays0.0
    names = dict(seats)
    if len(facts.alive_ids) == 1:
        name = names[facts.alive_ids[0]][:16]
        text, color = f'{name} alive | survive {seconds:.1f}s to settle', 3
    elif not facts.alive_ids:
        text, color = f'Both destroyed | settling {seconds:.1f}s | no points', 8
    else:
        text, color = f'Settling {seconds:.1f}s | result pending', 5
    return (('rect', x, y, width, 4, 5),
            ('rect', x+1, y+1, filled, 2, 10),
            ('rectb', x, y, width, 4, 0),
            ('text', x, y+text_gap, text[:width//4], color))
