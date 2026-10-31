"""Batch ABI for the unchanged native60Hz world; no policy or optimizer."""
import ctypes
import hashlib
import json
from pathlib import Path

import numpy as np

PROFILE_KEYS = ('game_step_seconds', 'observation_encode_seconds', 'dodge_seconds',
                'reset_seconds', 'total_slot_step_seconds')


class NativeSource60Vec:
    obs_dim, schema_version, actions = 1028, 24, 18
    episode_frames, grace_frames = 1800, 300

    def __init__(self, count, seed, weights=(1., 0., 0.), threads=4, *, assets):
        if (type(count) is not int or not 1 <= count <= 128 or type(seed) is not int
                or not 0 <= seed < 2**32 or type(threads) is not int or threads not in (1, 4, 8, 16)
                or tuple(weights) != (1., 0., 0.)):
            raise ValueError('1..128 environments, uint32 seed,1/4/8/16workers and pureLaika required')
        assets = Path(assets).resolve()
        manifest = json.loads((assets/'manifest.json').read_text())
        library = assets/manifest['library']
        if hashlib.sha256(library.read_bytes()).hexdigest() != manifest['library_sha256']:
            raise RuntimeError('batch library hash mismatch')
        self.lib = ctypes.CDLL(str(library))
        pointer = ctypes.c_void_p
        self.lib.kf60_vec_abi.argtypes, self.lib.kf60_vec_abi.restype = [], ctypes.c_uint32
        if self.lib.kf60_vec_abi() != 1:
            raise RuntimeError('batch ABI mismatch')
        self.lib.kf60_vec_new.argtypes = [ctypes.c_uint32]*3
        self.lib.kf60_vec_new.restype = pointer
        self.lib.kf60_vec_free.argtypes, self.lib.kf60_vec_free.restype = [pointer], None
        self.lib.kf60_vec_step.argtypes = [pointer, ctypes.POINTER(ctypes.c_uint16)]
        self.lib.kf60_vec_step.restype = ctypes.c_int
        self.lib.kf60_vec_reset_done.argtypes = [pointer]
        self.lib.kf60_vec_reset_done.restype = ctypes.c_int
        self.lib.kf60_vec_read.argtypes = [pointer, ctypes.POINTER(ctypes.c_float),
                                         ctypes.POINTER(ctypes.c_uint8), ctypes.POINTER(ctypes.c_double)]
        self.lib.kf60_vec_read.restype = ctypes.c_int
        self.lib.kf60_vec_profile.argtypes = [pointer, ctypes.POINTER(ctypes.c_double)]
        self.lib.kf60_vec_profile.restype = ctypes.c_int
        self.count, self.seed, self.weights, self.threads = count, seed, tuple(weights), threads
        self.obs, self.masks = np.empty((count, 1028), np.float32), np.empty((count, 10), np.uint8)
        self._info = np.empty((count, 24), np.float64)
        self.rewards = np.zeros(count, np.float32)
        self.dones, self.terminals, self.outcomes, self.opponents = (np.zeros(count, np.uint8) for _ in range(4))
        self.frames, self.action_changes, self.shots, self.hits = (np.zeros(count, np.uint32) for _ in range(4))
        self.needs_action = np.zeros(count, np.uint8)
        self.episodes = np.zeros(count, np.uint64)
        self.handle = self.lib.kf60_vec_new(count, seed, threads)
        if not self.handle:
            raise RuntimeError('native batch allocation refused')
        try:
            self._read()
        except BaseException:
            self.close()
            raise

    def _open(self):
        if not self.handle:
            raise RuntimeError('batch environment is closed')

    def _read(self):
        self._open()
        result = self.lib.kf60_vec_read(self.handle,
            self.obs.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
            self.masks.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
            self._info.ctypes.data_as(ctypes.POINTER(ctypes.c_double)))
        if result != 0 or not np.isfinite(self.obs).all() or not np.all(self._info[:, 0] == 1):
            raise RuntimeError('invalid batch read')

    def step(self, actions, opponent_actions=None):
        self._open()
        values = np.asarray(actions)
        if (values.shape != (self.count,) or values.dtype.kind not in 'iu'
                or np.any(values < 0) or np.any(values >= 18) or opponent_actions is not None):
            raise ValueError('one valid source action per learner; no external opponent')
        packed = np.ascontiguousarray(values, np.uint16)
        active = self.dones == 0
        before = self._info[:, 4:6].copy()
        if self.lib.kf60_vec_step(self.handle, packed.ctypes.data_as(ctypes.POINTER(ctypes.c_uint16))) != 0:
            raise RuntimeError('batch step refused')
        self._read()
        info = self._info
        self.terminals.fill(0)
        self.rewards.fill(0)
        self.shots.fill(0)
        self.hits.fill(0)
        self.rewards[active] = info[active, 3]
        self.dones[active] = info[active, 2] != 0
        self.terminals[active] = self.dones[active]
        self.outcomes[active] = info[active, 2]
        self.frames[active], self.action_changes[active] = info[active, 1], info[active, 6]
        self.shots[active], self.hits[active] = (info[active, 4:6]-before[active]).T

    def reset_done(self):
        self._open()
        ended = self.dones != 0
        if not ended.any():
            return
        if self.lib.kf60_vec_reset_done(self.handle) != 0:
            raise RuntimeError('batch reset refused')
        self._read()
        self.episodes[ended] += 1
        self.dones[ended] = 0
        # Match the legacy trainer buffers: only obs/masks/dones change on reset.

    def profile(self):
        self._open()
        values = np.empty(5, np.float64)
        if self.lib.kf60_vec_profile(self.handle,
                                    values.ctypes.data_as(ctypes.POINTER(ctypes.c_double))) != 0:
            raise RuntimeError('batch profile refused')
        return dict(zip(PROFILE_KEYS, values.tolist(), strict=True))

    def close(self):
        if getattr(self, 'handle', None):
            self.lib.kf60_vec_free(self.handle)
            self.handle = None
