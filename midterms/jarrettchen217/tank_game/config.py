"""Validated parameters for the deterministic simulation."""

import math
from dataclasses import dataclass, fields


def _finite_number(name: str, value: object) -> None:
    if type(value) not in (int, float):
        raise TypeError(f'{name} must be a number')
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError(f'{name} must be finite')


@dataclass(frozen=True)
class GameConfig:
    """Proposed defaults; all rates, dimensions and limits must be positive."""

    tank_radius: float = 8.0
    forward_speed: float = 45.0
    reverse_speed: float = 35.0
    turn_speed_deg: float = 180.0
    tick_rate: int = 60
    bullet_radius: float = 1.5
    bullet_speed: float = 90.0
    bullet_lifetime: float = 10.0
    fire_interval: float = .25
    max_bullets: int = 5
    explosion_duration: float = .35

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name in ('tick_rate', 'max_bullets') and type(value) is not int:
                raise TypeError(f'{field.name} must be an integer')
            _finite_number(field.name, value)
            if value <= 0:
                raise ValueError(f'{field.name} must be positive')
