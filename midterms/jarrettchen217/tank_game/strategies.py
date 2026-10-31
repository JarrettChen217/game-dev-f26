"""Fresh versioned policies; pursuit alone is an internal evaluation ablation."""

from tank_game.laika import LaikaPolicy
from tank_game.patrol import SimplePatrol
from tank_game.prediction import HardPolicy
from tank_game.pursuit import PursuitPolicy

POLICIES={'simple':SimplePatrol,'hard':HardPolicy,'pursuit':PursuitPolicy,'laika':LaikaPolicy}


def make_policy(name):
    if name not in POLICIES:
        raise ValueError(f'unknown strategy: {name}')
    return POLICIES[name]()
