"""Immutable simulation records with no input or rendering dependency."""

from dataclasses import dataclass

from tank_game.config import _finite_number


def _identity(name: str, value: object, *, allow_empty: bool = False) -> None:
    if type(value) is not str:
        raise TypeError(f'{name} must be a string')
    if not allow_empty and not value:
        raise ValueError(f'{name} must not be empty')


def _positive(name: str, value: object) -> None:
    _finite_number(name, value)
    if value <= 0:
        raise ValueError(f'{name} must be positive')


def _nonnegative(name: str, value: object) -> None:
    _finite_number(name, value)
    if value < 0:
        raise ValueError(f'{name} must not be negative')


@dataclass(frozen=True)
class TankState:
    """A tank's data; only its owning simulation replaces this record."""

    id: str
    x: float
    y: float
    heading_deg: float
    alive: bool = True
    radius: float = 8.0
    cooldown_remaining: float = 0.0

    def __post_init__(self) -> None:
        _identity('id', self.id)
        for name in ('x', 'y', 'heading_deg'):
            _finite_number(name, getattr(self, name))
        if type(self.alive) is not bool:
            raise TypeError('alive must be a boolean')
        _positive('radius', self.radius)
        _nonnegative('cooldown_remaining', self.cooldown_remaining)
        object.__setattr__(self, 'heading_deg', (self.heading_deg % 360) % 360)


@dataclass(frozen=True)
class BulletState:
    """Simulation-owned projectile pose and private ownership/lifetime metadata."""

    id: str
    x: float
    y: float
    vx: float
    vy: float
    radius: float = 1.5
    owner_id: str = ''
    age: float = 0.0

    def __post_init__(self) -> None:
        _identity('id', self.id)
        _identity('owner_id', self.owner_id, allow_empty=True)
        for name in ('x', 'y', 'vx', 'vy'):
            _finite_number(name, getattr(self, name))
        _positive('radius', self.radius)
        _nonnegative('age', self.age)
