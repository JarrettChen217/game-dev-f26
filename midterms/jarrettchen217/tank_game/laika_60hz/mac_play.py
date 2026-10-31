"""Four selected opponents over one retained native60Hz Training/Game.

Legacy HybridPlay names remain compatible with the saved menu/play handoff.
"""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

if sys.platform != 'emscripten':
    import ctypes

from tank_game.actions import Action, validate_request
from tank_game.laika_60hz.session import Source60RoundSession
from tank_game.laika_60hz.world import World60
from tank_game.match_hud import SessionScore
from tank_game.models.registry import load_hybrid
from tank_game.original_laika.session import OriginalRecord
from tank_game.original_laika.world import validate_seed

ROOT = Path(__file__).resolve().parents[2]
# Course folder: the play bridge is built into the package (scripts/build_native.py).
ASSETS = Path(__file__).resolve().parent/'play'
CHECKPOINT = ROOT/'reports/source60-hybrid/overnight-20261029-backup/snapshot/endpoint-u19588/live.pt'
LIVE_SHA = 'b1f1ee503cb41cb5e90f92c9e31cd9621f646f7c545f033b5d02eb9f59dcaac8'
CONTRACT = 'a5b28a10b4f65567c272b9307a6e68a5162c2ff8a06d35f2fba8a94155f96d75'


def verified_checkpoint(path):
    path = Path(path).resolve()
    if hashlib.sha256(path.read_bytes()).hexdigest() != LIVE_SHA:
        raise ValueError('u19588 checkpoint SHA256 mismatch')
    meta = json.loads(path.with_suffix('.json').read_text())
    if (meta.get('update') != 19588 or meta.get('trained_steps') != 96529664
            or meta.get('environment_contract_sha256') != CONTRACT
            or meta.get('arch') != 'hybrid_schema24_reconstructed_v1'):
        raise ValueError('u19588 source60 provenance mismatch')
    return path


def ReleasedPolicy(checkpoint=None):
    """Selected Hybrid model: manifest registry by default, Torch only for an explicit research checkpoint."""
    return TorchCheckpointPolicy(checkpoint) if checkpoint is not None else load_hybrid()


class TorchCheckpointPolicy:
    def __init__(self, checkpoint=CHECKPOINT):
        path = verified_checkpoint(checkpoint)
        import torch

        from tank_game.laika_60hz.training.ppo import ARCH, HybridActorCritic
        torch.set_num_threads(1)
        payload = torch.load(path, map_location='cpu', weights_only=True)
        if payload['arch'] != ARCH:
            raise ValueError('model architecture mismatch')
        self.model = HybridActorCritic().eval()
        self.model.load_state_dict(payload['model'], strict=True)
        self.model.requires_grad_(False)
        self.calls = 0

    def action(self, features, mask):
        import torch
        with torch.inference_mode():
            logits, _ = self.model(torch.from_numpy(features.copy()).unsqueeze(0),
                                   torch.from_numpy(mask.astype(bool)).unsqueeze(0))
            if not torch.isfinite(logits).all():
                raise FloatingPointError('nonfinite model logits')
            action = int(logits.argmax(-1).item())
        self.calls += 1
        return action


class PlayBridge:
    def __new__(cls, *args, **kwargs):
        if sys.platform == 'emscripten':
            from web.source60_bridge import BrowserPlayBridge
            return BrowserPlayBridge(*args, **kwargs)
        return super().__new__(cls)

    def __init__(self, policy, mode='human', assets=ASSETS, strategy='hybrid', fixture=0):
        if mode not in ('human', 'watch'):
            raise ValueError('choose human or watch')
        self.policy, self.mode, self.strategy = policy, mode, strategy
        self.opponent_action = Action()
        self.fixture = fixture
        self.assets = Path(assets)
        manifest = json.loads((self.assets/'manifest.json').read_text())
        library = self.assets/'play.dylib'
        if hashlib.sha256(library.read_bytes()).hexdigest() != manifest['library_sha256']:
            raise RuntimeError('Mac play library SHA mismatch; rebuild it')
        self.lib = ctypes.CDLL(str(library))
        pointer = ctypes.c_void_p
        self.lib.kf60_play_new.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
        self.lib.kf60_play_new.restype = pointer
        self.lib.kf60_play_fixture.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
        self.lib.kf60_play_fixture.restype = pointer
        self.lib.kf60_play_facts.argtypes = [pointer, ctypes.POINTER(ctypes.c_double), ctypes.c_size_t]
        self.lib.kf60_play_facts.restype = ctypes.c_size_t
        self.lib.kf60_play_opponent.argtypes = [pointer, ctypes.c_uint32]
        self.lib.kf60_play_opponent.restype = ctypes.c_int
        self.lib.kf60_play_free.argtypes = [pointer]
        self.lib.kf60_play_free.restype = None
        self.lib.kf60_play_step.argtypes = [pointer, ctypes.c_uint16, ctypes.c_uint16]
        self.lib.kf60_play_step.restype = ctypes.c_int
        self.lib.kf60_play_read.argtypes = [pointer, ctypes.POINTER(ctypes.c_float),
                                          ctypes.POINTER(ctypes.c_uint8), ctypes.POINTER(ctypes.c_double)]
        self.lib.kf60_play_read.restype = None
        self.lib.kf60_play_snapshot.argtypes = [pointer, ctypes.POINTER(ctypes.c_double), ctypes.c_size_t]
        self.lib.kf60_play_snapshot.restype = ctypes.c_size_t
        # Practice/lessons expose host facts only, never stale/fabricated learner vectors.
        self.features, self.mask = ((None, None) if fixture else
                                    (np.empty(1028, np.float32), np.empty(10, np.uint8)))
        self.info = None if fixture else np.empty(24, np.float64)
        self.buffer = (ctypes.c_double*8192)()
        self.handle, self.calls = None, 0
        self.diagnostics = {}

    def call(self, operation, **kwargs):
        if operation == 'init':
            candidate = (self.lib.kf60_play_fixture(kwargs['seed'], self.fixture) if self.fixture
                         else self.lib.kf60_play_new(kwargs['seed'], int(self.mode == 'human')))
            if not candidate:
                raise RuntimeError('play engine allocation failed')
            if self.lib.kf60_play_opponent(candidate, int(self.strategy == 'laika')) != 1:
                self.lib.kf60_play_free(candidate)
                raise RuntimeError('play controller selection failed')
            self.close(); self.handle = candidate
            self.opponent_action = Action()
        elif operation == 'step' and self.handle:
            a = self.opponent_action
            actor = (self.policy.action(self.features, self.mask) if self.strategy == 'hybrid'
                     else (a.throttle+1)*6+(a.turn+1)*2+int(a.fire))
            if isinstance(actor, bool) or not isinstance(actor, (int, np.integer)) or not 0 <= actor < 18:
                raise ValueError('policy must return one strict action in0..17')
            throttle, turn, fire = kwargs['action']
            human = (throttle+1)*6+(turn+1)*2+int(fire)
            result = self.lib.kf60_play_step(self.handle, actor, human)
            if result != 1:
                raise RuntimeError('play step rejected or round ended')
            self.calls += 1
            self.last_opponent_action = actor
            self.opponent_action = Action()
        else:
            raise RuntimeError('closed or invalid play operation')
        if not self.fixture:
            self.lib.kf60_play_read(self.handle, self.features.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                                   self.mask.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
                                   self.info.ctypes.data_as(ctypes.POINTER(ctypes.c_double)))
            if self.info[0] != 1 or not np.isfinite(self.features).all():
                raise RuntimeError('play observation ABI mismatch')
        n = self.lib.kf60_play_snapshot(self.handle, self.buffer, len(self.buffer))
        if not 8 <= n <= len(self.buffer) or self.buffer[0] != 1:
            raise RuntimeError('play render ABI mismatch')
        raw = list(self.buffer[:n])
        n = self.lib.kf60_play_facts(self.handle, self.buffer, len(self.buffer))
        if not 9 <= n <= len(self.buffer) or self.buffer[0] != 1:
            raise RuntimeError('play facts ABI mismatch')
        from tank_game.laika_60hz.play_packet import decode_packet
        packet, self.facts, self.diagnostics = decode_packet(
            raw, list(self.buffer[:n]), calls=self.calls, strategy=self.strategy,
            action=getattr(self, 'last_opponent_action', 8))
        return packet

    def close(self):
        if self.handle:
            self.lib.kf60_play_free(self.handle); self.handle = None


class HybridPlayWorld(World60):
    def __init__(self, seed=1000, *, policy=None, mode='human', assets=ASSETS, strategy='hybrid', fixture=0):
        validate_seed(seed)
        if strategy not in ('simple', 'hard', 'laika', 'hybrid'):
            raise ValueError('choose Simple, Hard, Laika or Hybrid')
        if mode == 'watch' and strategy != 'hybrid':
            raise ValueError('watch mode is Hybrid versus Laika')
        self.seed, self.mode, self.strategy = seed, mode, strategy
        selected = policy if policy is not None else ReleasedPolicy() if strategy == 'hybrid' else None
        self.model_label = getattr(selected, 'label', 'u19588')
        self._bridge = PlayBridge(selected, mode, assets, strategy, fixture)
        self._opponent_pending = False
        try:
            self._packet = self._bridge.call('init', seed=seed)
        except BaseException:
            self._bridge.close()
            raise
        self._manifest = {'wasm_sha256': None}
        if sys.platform == 'emscripten':
            from js import window
            self._source_manifest = {'library_sha256': str(window.tankSource60Sha),
                                     'target': 'wasm32-unknown-unknown'}
        else:
            self._source_manifest = json.loads((Path(assets)/'manifest.json').read_text())
        self._round_id, self._tick, self._rejected = 1, 0, 0
        self._pending, self._deaths, self._previous, self._closed = None, {}, self._packet, False
        self.presentation_seats = (('tank-1', 'YOU' if mode == 'human' else 'Laika'),
                                   ('tank-2', self.model_label.upper() if strategy == 'hybrid' else strategy.capitalize()))

    def observe(self, self_id):
        scene = super().observe(self_id)
        scene['controller_roles'] = {'tank-1': 'human' if self.mode == 'human' else 'source-laika-60hz',
                                     'tank-2': {'hybrid': 'hybrid-'+self.model_label, 'laika': 'source-laika-60hz'}.get(self.strategy, self.strategy)}
        scene['presentation_heading'] = (f'YOU / {self.strategy.upper()}' + (' '+self.model_label if self.strategy == 'hybrid' else '') if self.mode == 'human'
                                         else f'WATCH: HYBRID {self.model_label} / Laika')
        scene['presentation_mode'] = self.mode
        scene['presentation_strategy'] = 'Hybrid '+self.model_label if self.strategy == 'hybrid' else self.strategy.capitalize()
        return scene


    def submit_action(self, source_id, data):
        if source_id != 'tank-2' or self.strategy not in ('simple', 'hard'):
            return super().submit_action(source_id, data)
        action = validate_request(data, source_id=source_id, round_id=self._round_id, tick=self._tick)
        if (self._closed or self._opponent_pending or action is None
                or not self.observe(source_id)['self_status']['alive'] or self.raw_render[14]):
            self._rejected += 1
            return Action()
        self._bridge.opponent_action, self._opponent_pending = action, True
        return action

    def step(self):
        super().step()
        self._opponent_pending = False

    def restart(self, **kwargs):
        changed = super().restart(**kwargs)
        if changed:
            self._opponent_pending = False
        return changed


class HybridPlaySession(Source60RoundSession):
    def __init__(self, seed=1000, *, policy=None, mode='human', assets=ASSETS, world=None,
                 random_map=True, strategy='hybrid', practice=False):
        self.random_map = random_map
        if practice and world is None:
            from tank_game.laika_60hz.play_modes import SoloPlayWorld
            world = SoloPlayWorld(seed)
        self.world = world if world is not None else HybridPlayWorld(seed, policy=policy, mode=mode, assets=assets, strategy=strategy)
        self.record = OriginalRecord(self.world.seed, 'killfield-source-60hz')
        self.score = None if practice else SessionScore(('tank-1', 'tank-2'))
        self.last_error, self._closed = None, False

    def transition(self, operation, *, allow_active=False):
        if operation == 'next_map' and not self.random_map:
            return False
        return super().transition(operation, allow_active=allow_active)

    def record_result(self):
        return super().record_result() if self.score is not None else None

    def close(self):
        if self.score is None:
            self._closed = True
            self.world.close()
        else:
            super().close()
