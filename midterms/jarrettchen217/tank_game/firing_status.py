"""Read-only firing eligibility and projectile timers from the public snapshot."""
from dataclasses import dataclass


@dataclass(frozen=True)
class BulletLifetime:
    id: str
    remaining_seconds: float
    fraction: float


@dataclass(frozen=True)
class FiringStatus:
    can_fire: bool
    cooldown_remaining: float
    active_bullets: int
    capacity: int
    free_slots: int
    reasons: tuple[str, ...]
    bullets: tuple[BulletLifetime, ...]


def _bullet_key(bullet):
    identity=bullet['id']
    suffix=identity.removeprefix('bullet-')
    return (0,int(suffix)) if identity.startswith('bullet-') and suffix.isdigit() else (1,identity)


def make_firing_status(scene: dict) -> FiringStatus:
    own=scene['self_status']
    capacity=scene['rules']['max_bullets']
    free=max(0,capacity-own['active_bullets'])
    cooldown=own['cooldown_remaining']
    if scene['round_status']!='PLAYING' or not own['alive']:
        reasons=('Round ended - timers frozen',)
    elif not own.get('trigger_released', True):
        reasons=('Release fire before the next shot',)
    elif free==0 and cooldown>0:
        reasons=('Slots full; cooling down',)
    elif free==0:
        reasons=('Waiting for a bullet to disappear',)
    elif cooldown>0:
        reasons=('Cooling down',)
    else:
        reasons=('Ready; a clear muzzle is required',)
    lifetime=scene['rules']['bullet_lifetime']
    rows=tuple(BulletLifetime(b['id'],b['remaining_lifetime'],
                             max(0,min(1,b['remaining_lifetime']/lifetime)))
               for b in sorted(scene['bullets'],key=_bullet_key))
    return FiringStatus(own['can_fire'],cooldown,own['active_bullets'],capacity,
                        free,reasons,rows)
