"""Real Rust source60Hz -> schema24 features/masks; no policy or optimizer."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
from typing import ClassVar

import numpy as np

ASSETS = Path(os.environ.get('TANK_SOURCE60_TRAINING_ASSETS', Path(__file__).resolve().parent)).resolve()
OUTCOMES = ('running', 'win', 'loss', 'double', 'draw')


class Source60HybridEnv:
    metadata: ClassVar[dict] = {'render_modes': []}

    def __init__(self, *, external_tick_limit=None):
        if external_tick_limit is not None and (type(external_tick_limit) is not int or external_tick_limit <= 0):
            raise ValueError('external limit must be a positive integer')
        manifest = json.loads((ASSETS/'manifest.json').read_text())
        library = ASSETS/manifest['library']
        if hashlib.sha256(library.read_bytes()).hexdigest() != manifest['library_sha256']:
            raise RuntimeError('prepared training library hash mismatch')
        self.lib = ctypes.CDLL(str(library))
        actual = []
        for name in ('schema', 'features', 'masks', 'actions'):
            function = getattr(self.lib, 'kf60_train_'+name)
            function.argtypes, function.restype = [], ctypes.c_uint32
            actual.append(function())
        if actual != [24, 1028, 10, 18]:
            raise RuntimeError('native schema24 ABI mismatch')
        pointer = ctypes.c_void_p
        self.lib.kf60_train_new.argtypes = [ctypes.c_uint32]
        self.lib.kf60_train_new.restype = pointer
        self.lib.kf60_train_free.argtypes, self.lib.kf60_train_free.restype = [pointer], None
        self.lib.kf60_train_step.argtypes, self.lib.kf60_train_step.restype = [pointer, ctypes.c_uint16], ctypes.c_int
        self.lib.kf60_train_read.argtypes = [pointer, ctypes.POINTER(ctypes.c_float),
                                            ctypes.POINTER(ctypes.c_uint8), ctypes.POINTER(ctypes.c_double)]
        self.lib.kf60_train_read.restype = None
        self._features = np.empty(1028, np.float32)
        self._mask = np.empty(10, np.uint8)
        self._info = np.empty(24, np.float64)
        self.handle = None
        self._closed, self._done, self._seed = False, True, 1000
        self.external_tick_limit = external_tick_limit
        self.action_count = 18

    def _read(self):
        if not self.handle:
            raise RuntimeError('reset an open environment first')
        self.lib.kf60_train_read(self.handle,
            self._features.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
            self._mask.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
            self._info.ctypes.data_as(ctypes.POINTER(ctypes.c_double)))
        if self._info[0] != 1 or not np.isfinite(self._features).all():
            raise RuntimeError('invalid native observation')

    def observe(self):
        self._read()
        return {'features': self._features.copy(), 'mask': self._mask.copy()}

    def state(self):
        self._read()
        i = self._info
        return {'profile': 'source60-schema24-prep-v1', 'seed': self._seed,
                'tick': int(i[1]), 'elapsed_seconds': i[1]/60, 'outcome': OUTCOMES[int(i[2])],
                'reward': float(i[3]), 'shots': int(i[4]), 'hits': int(i[5]), 'action_changes': int(i[6]),
                'learner_seat': 0, 'learner_pose': tuple(i[7:10]), 'learner_alive': bool(i[10]),
                'opponent_pose': tuple(i[11:14]), 'opponent_alive': bool(i[14]),
                'internal_ai_seats': tuple(n for n in range(2) if i[15+n]),
                'laika_calls': int(i[17]), 'end_count': int(i[18]), 'frozen': bool(i[19]),
                'last_action': int(i[20]), 'history_frames': int(i[21]), 'idle_streak': int(i[22])}

    def reset(self, *, seed=None, options=None):
        if self._closed:
            raise RuntimeError('environment closed')
        selected = self._seed if seed is None else seed
        if type(selected) is not int or not 0 <= selected < 2**32 or options not in (None, {}):
            raise ValueError('reset requires a uint32 seed and no custom options')
        candidate = self.lib.kf60_train_new(selected)
        if not candidate:
            raise RuntimeError('native allocation failed')
        if self.handle:
            self.lib.kf60_train_free(self.handle)
        self.handle, self._seed, self._done = candidate, selected, False
        return self.observe(), self.state()

    def step(self, action):
        if self._closed or self._done:
            raise RuntimeError('reset before another step')
        if (isinstance(action, (bool, np.bool_)) or not isinstance(action, (int, np.integer))
                or not 0 <= int(action) < 18):
            raise ValueError('action must be an integer in0..17')
        if self.lib.kf60_train_step(self.handle, int(action)) != 1:
            raise RuntimeError('native step refused')
        observation, info = self.observe(), self.state()
        terminated = info['outcome'] != 'running'
        truncated = bool(not terminated and self.external_tick_limit is not None
                         and info['tick'] >= self.external_tick_limit)
        self._done = terminated or truncated
        info['bootstrap_allowed'] = not terminated
        return observation, info['reward'], terminated, truncated, info

    def close(self):
        if self.handle:
            self.lib.kf60_train_free(self.handle)
            self.handle = None
        self._closed = self._done = True
