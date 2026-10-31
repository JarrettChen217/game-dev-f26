"""Lazy source-checkout integration of the accepted local fixed Hybrid model.

No weights, downloads, new model contract or alternate simulation live here.
The published actor's original MIT provenance is retained in tank_transfer.
"""
import sys
from importlib import import_module
from pathlib import Path

from tank_game.killfield_rules import rules_episode

DEFAULT_ASSETS = Path(__file__).resolve().parents[1] / 'reports/killfield-author/viewer-v17b'


def hybrid_episode(game_map=None, *, spawns=None, round_limit=120):
    spec = rules_episode(game_map, spawns=spawns, round_limit=round_limit)
    if spec.game_map.columns > 12 or spec.game_map.rows > 10:
        raise ValueError('Hybrid supports maps up to 12 by 10 cells. Choose a supported map or Simple/Hard.')
    return spec


def load_hybrid_factory(assets=None):
    """One immutable actor per owned session; each round gets a fresh encoder."""
    if getattr(sys, 'frozen', False):
        raise ValueError('Hybrid uses local source-checkout model files. Choose Simple or Hard in this build.')
    try:
        actor_module = import_module('research.killfield.tank_transfer.actor')
        adapter = import_module('research.killfield.tank_transfer.adapter')
    except ImportError as error:
        raise ValueError('Hybrid needs the existing NumPy runtime. Choose Simple or Hard.') from error
    try:
        actor = actor_module.FrozenActor(DEFAULT_ASSETS if assets is None else assets)
    except OSError as error:
        raise ValueError('Hybrid model files are missing. Restore the local v17b assets, or choose Simple/Hard.') from error
    except ValueError as error:
        raise ValueError('Hybrid model files failed the v17b integrity check. Restore approved assets or choose Simple/Hard.') from error
    return lambda: adapter.HybridController(actor, profile=adapter.RULES_PROFILE)
