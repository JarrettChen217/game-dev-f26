"""NumPy-only thin forward port of Cichlider/killfield viewer/src/hybrid.js.

Source MIT; see README provenance. Frozen external weights are never distributed
by this module. Each layer rounds to float32 like the original JS implementation.
"""

import hashlib
import json
from pathlib import Path

import numpy as np

WEIGHTS_SHA256 = "96d48cdfcd9a86e6cdcb841af5f6da173f47aa7e26a7fd167b80292a11bad83c"


class FrozenActor:
    def __init__(self, assets):
        assets = Path(assets)
        manifest_raw = (assets / "assets/hybrid.json").read_bytes()
        if hashlib.sha256(manifest_raw).hexdigest() != (
            "05e69111a975ce7df69ee52678eb46716f448171f3c620f09d0e182f4002952c"
        ):
            raise ValueError("expected the published v17b tensor layout")
        self.manifest = json.loads(manifest_raw)
        raw = (assets / "assets/hybrid.bin").read_bytes()
        if hashlib.sha256(raw).hexdigest() != WEIGHTS_SHA256:
            raise ValueError("expected the frozen published v17b actor")
        m = self.manifest
        if (m["schema"], m["observation"], m["actions"], m["floats"]) != (24, 1028, 18, 261501):
            raise ValueError("actor schema mismatch")
        self.weights = np.frombuffer(raw, dtype="<f4")
        self.tensors = {}
        for name, spec in m["tensors"].items():
            value = self.weights[spec["offset"] : spec["offset"] + spec["length"]].reshape(
                spec["shape"]
            )
            # JS multiplies/adds in Number precision, then stores each layer as f32.
            self.tensors[name] = value.astype(np.float64)

    def dense(self, x, prefix, activation=None):
        y = self.tensors[prefix + ".weight"] @ x.astype(np.float64) + self.tensors[prefix + ".bias"]
        if activation == "relu":
            y = np.maximum(0, y)
        if activation == "tanh":
            y = np.tanh(y)
        return y.astype(np.float32)

    def conv(self, x, prefix, stride):
        padded = np.pad(x, ((0, 0), (1, 1), (1, 1)))
        windows = np.lib.stride_tricks.sliding_window_view(padded, (3, 3), axis=(1, 2))
        windows = windows[:, ::stride, ::stride].astype(np.float64)
        y = np.einsum("oikl,iyxkl->oyx", self.tensors[prefix + ".weight"], windows, optimize=True)
        return np.maximum(0, y + self.tensors[prefix + ".bias"][:, None, None]).astype(np.float32)

    def logits(self, observation, mask, dodge):
        obs = np.asarray(observation, dtype=np.float32)
        mask = np.asarray(mask, dtype=bool)
        dodge = np.asarray(dodge, dtype=np.float32)
        if (
            obs.shape != (1028,)
            or mask.shape != (10,)
            or dodge.shape != (9,)
            or not np.isfinite(obs).all()
            or not np.isfinite(dodge).all()
        ):
            raise ValueError("invalid actor inputs")
        grid = obs[:840].reshape(12, 10, 7).transpose(2, 0, 1)
        c1 = self.conv(grid, "map.0", 1)
        c2 = self.conv(c1, "map.2", 2)
        grid = self.dense(c2.reshape(-1), "map.5", "tanh")
        mean = np.zeros(32, dtype=np.float32)
        peak = np.zeros(32, dtype=np.float32)
        for row in obs[900:1000].reshape(10, 10)[mask]:
            encoded = self.dense(self.dense(row, "bullets.0", "relu"), "bullets.2", "relu")
            mean += encoded
            peak = np.maximum(peak, encoded)
        if mask.sum():
            mean /= mask.sum()
        scalars = self.dense(np.concatenate((obs[840:900], obs[1000:])), "scalars.0", "tanh")
        features = self.dense(np.concatenate((grid, scalars, mean, peak)), "trunk.0", "tanh")
        logits = self.dense(features, "actor")
        dodge_scale = float(self.tensors["dodge_alpha_old"]) + float(
            self.dense(self.dense(features, "dodge_delta.0", "tanh"), "dodge_delta.2")[0]
        )
        ammo_scale, quality, lock, suicide_scale = self.tensors["ammo_alpha_old"] + self.dense(
            self.dense(features, "ammo_delta.0", "tanh"), "ammo_delta.2"
        )
        ammo, hit, suicide, eta = map(float, (obs[863], obs[890], obs[891], obs[893]))
        hit_soon = hit * (1 - max(0, min(1, eta * 3)))
        fire_bias = (
            ammo_scale * ammo
            + quality * hit_soon
            - lock * (1 - ammo) ** 2 * (1 - hit_soon)
            - suicide_scale * suicide
        )
        for action in range(18):
            logits[action] = float(logits[action]) + dodge_scale * float(dodge[action // 2])
            if action % 2:
                logits[action] = float(logits[action]) + fire_bias
        idle = max(0, min(1, (float(obs[1027]) * 25 - 8) / 17))
        for action in (8, 9):
            logits[action] = float(logits[action]) - idle * float(
                self.tensors["idle_logit_penalty"]
            )
        if not np.isfinite(logits).all():
            raise ValueError("nonfinite actor output")
        return logits
