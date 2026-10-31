"""One loading entry for the Hybrid opponent on desktop and in the browser.

Selection order: explicit path, then TANK_HYBRID_MODEL, then active.json.
A model is a manifest JSON plus a little-endian float32 tensor file (by default
the manifest's sibling .bin). It is checked against the game ABI in contract.py
before play; a rejected non-default model falls back to the bundled default and
is labeled as a fallback, never as the requested model.
"""
import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np

from research.killfield.tank_transfer.actor import FrozenActor
from tank_game.models import contract

MODELS = Path(__file__).resolve().parent
ACTIVE = MODELS/'active.json'
ENVIRONMENT = 'TANK_HYBRID_MODEL'


class ModelContractError(ValueError):
    """The manifest or tensors do not match the Hybrid game ABI."""


def default_manifest():
    return (MODELS/json.loads(ACTIVE.read_text())['hybrid']).resolve()


def resolve_manifest(path=None):
    selected = path or os.environ.get(ENVIRONMENT)
    return Path(selected).resolve() if selected else default_manifest()


class ManifestActor(FrozenActor):
    """NumPy-only inference over a manifest-declared, ABI-checked tensor file."""

    def __init__(self, manifest_path):
        self.manifest_path = Path(manifest_path).resolve()
        try:
            self._load()
        except ModelContractError:
            raise
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            raise ModelContractError(f'malformed model {self.manifest_path}: {type(error).__name__}: {error}') from None
        self.model_id = str(self.manifest.get('label') or f"u{self.manifest.get('update')}")
        self.fallback_from = None
        self.calls = 0

    def _load(self):
        manifest = json.loads(self.manifest_path.read_text())
        if not isinstance(manifest, dict):
            raise ModelContractError('model manifest must be a JSON object')
        expected = {'arch': contract.ARCH, 'schema': contract.SCHEMA, 'observation': contract.OBSERVATION,
                    'actions': contract.ACTIONS, 'environment_contract_sha256': contract.ENVIRONMENT_CONTRACT_SHA256}
        for key, value in expected.items():
            if manifest.get(key) != value:
                raise ModelContractError(f'model {key} is {manifest.get(key)!r}; this game requires {value!r}')
        weights = self.manifest_path.parent/manifest.get('weights', self.manifest_path.with_suffix('.bin').name)
        try:
            raw = weights.read_bytes()
        except OSError as error:
            raise ModelContractError(f'missing model tensors {weights}: {error}') from None
        if (len(raw) != manifest.get('bytes') or len(raw) != 4*manifest.get('floats')
                or hashlib.sha256(raw).hexdigest() != manifest.get('sha256')):
            raise ModelContractError('model tensor size or SHA256 does not match its manifest')
        tensors = manifest.get('tensors')
        if not isinstance(tensors, dict) or set(tensors) != contract.INFERENCE_KEYS:
            raise ModelContractError('model tensor set is not exactly the inference-only actor')
        self.manifest = manifest
        self.weights = np.frombuffer(raw, dtype='<f4')
        if not np.isfinite(self.weights).all():
            raise ModelContractError('nonfinite model weights')
        self.tensors, end = {}, 0
        for name in sorted(tensors, key=lambda n: tensors[n]['offset']):
            offset, length, shape = (tensors[name][k] for k in ('offset', 'length', 'shape'))
            if tuple(shape) != contract.INFERENCE_SHAPES[name]:
                raise ModelContractError(f'model tensor {name} has shape {shape}; this game requires '
                                         f'{list(contract.INFERENCE_SHAPES[name])}')
            if offset != end or length != int(np.prod(shape)) or offset+length > self.weights.size:
                raise ModelContractError(f'model tensor layout mismatch at {name}')
            self.tensors[name] = self.weights[offset:offset+length].reshape(shape).astype(np.float64)
            end += length
        if end != self.weights.size:
            raise ModelContractError('model tensor layout does not cover the weight file')
        # One zero-input decision before play, so a model never fails mid-match.
        self.logits(np.zeros(contract.OBSERVATION, np.float32), np.zeros(contract.BULLET_SLOTS, bool),
                    np.zeros(contract.ACTIONS//2, np.float32))

    @property
    def label(self):
        return self.model_id+(' (fallback)' if self.fallback_from else '')

    def action(self, features, mask):
        logits = self.logits(features, mask, np.asarray(features)[1018:1027])
        self.calls += 1
        return int(np.argmax(logits))


def load_hybrid(path=None, *, fallback=True):
    """Load the selected model; a rejected non-default model falls back to the default."""
    selected = resolve_manifest(path)
    try:
        return ManifestActor(selected)
    except ModelContractError as error:
        if not fallback:
            raise
        default = default_manifest()
        if selected == default:
            raise
        print(f'Hybrid model rejected ({error}); using bundled default {default.parent.name}', file=sys.stderr)
        actor = ManifestActor(default)
        actor.fallback_from = (str(selected), str(error))
        return actor
