"""Tank-native constants; batch execution is an explicit isolated-assets opt-in."""
import os

from tank_game.laika_60hz.training.vector import Source60HybridVec


def DuelVec(count, seed, weights=(1., 0., 0.), threads=0):
    assets = os.environ.get('TANK_SOURCE60_BATCH_ASSETS')
    if assets:
        from tank_game.laika_60hz.training.batch import NativeSource60Vec
        return NativeSource60Vec(count, seed, weights, threads or 4, assets=assets)
    return Source60HybridVec(count, seed, weights, threads)

__all__ = ['DuelVec']

OBS_SCHEMA_VERSION, OBS_DIM, BULLET_SLOTS, ACTIONS = 24, 1028, 10, 18
MAP_W, MAP_H, MAP_CHANNELS = 12, 10, 7
MAP_DIM, BULLET_OFFSET, BULLET_DIM, SCALAR_DIM = 840, 900, 10, 88
OPPONENT_NAMES = {0: 'laika', 1: 'mpc', 2: 'frozen'}
