"""Headless rounds of the Hybrid player (u19588 by default) against native Laika.

The player only sees the schema24 observation (1028 float32) and bullet mask the
play bridge exposes, and only returns one of 18 actions; the engine owns state.

  smoke:  uv run --frozen python scripts/evaluate.py --seeds 1000
  suite:  uv run --frozen python scripts/evaluate.py --suite eval/heldout-suite-v1.json --out reports/heldout.json
  trace:  add --trace reports/trace.jsonl to log observation -> action for the first round
"""
import argparse
import ctypes
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tank_game.models.registry import load_hybrid

# schema24 layout (hybrid_obs.rs offsets); the 840-value maze grid [0, 840) is left out of traces.
CHANNELS = {'wall_rays': (840, 856), 'self': (856, 868), 'opponent': (868, 880), 'navigation': (880, 890),
            'aim_self': (890, 895), 'aim_opponent': (895, 900), 'bullets': (900, 1000), 'threat': (1000, 1003),
            'phase': (1003, 1007), 'last_action': (1007, 1010), 'self_threat_count': (1010, 1011),
            'older_actions': (1011, 1017), 'change_rate': (1017, 1018), 'dodge_outlook': (1018, 1027),
            'idle_streak': (1027, 1028)}
PLAY = ROOT/'tank_game/laika_60hz/play'
OUTCOMES = {1: 'win', 2: 'loss', 3: 'both_destroyed', 4: 'draw_time'}
LIMIT = 1800+300  # task frames plus the settlement grace window (duel.rs)
NEUTRAL = 8  # (throttle 0, turn 0, no fire) for the unused human seat


def bridge():
    manifest = json.loads((PLAY/'manifest.json').read_text())
    library = PLAY/'play.dylib'
    if hashlib.sha256(library.read_bytes()).hexdigest() != manifest['library_sha256']:
        raise RuntimeError('play.dylib does not match its manifest; run scripts/build_native.py')
    lib = ctypes.CDLL(str(library))
    p = ctypes.c_void_p
    lib.kf60_play_new.argtypes, lib.kf60_play_new.restype = [ctypes.c_uint32, ctypes.c_uint32], p
    lib.kf60_play_opponent.argtypes, lib.kf60_play_opponent.restype = [p, ctypes.c_uint32], ctypes.c_int
    lib.kf60_play_step.argtypes, lib.kf60_play_step.restype = [p, ctypes.c_uint16, ctypes.c_uint16], ctypes.c_int
    lib.kf60_play_read.argtypes = [p, ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_uint8),
                                   ctypes.POINTER(ctypes.c_double)]
    lib.kf60_play_free.argtypes = [p]
    return lib


def play_round(lib, policy, seed, trace=None):
    handle = lib.kf60_play_new(seed, 0)  # seat 0: the model, seat 1: native Laika
    features, mask, info = np.empty(1028, np.float32), np.empty(10, np.uint8), np.empty(24, np.float64)

    def read():
        lib.kf60_play_read(handle, features.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                           mask.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
                           info.ctypes.data_as(ctypes.POINTER(ctypes.c_double)))
    try:
        if lib.kf60_play_opponent(handle, 0) != 1:
            raise RuntimeError('could not keep seat 0 for the model')
        read()
        decisions, illegal, latency = 0, 0, []
        while info[2] == 0:
            if decisions >= LIMIT:
                raise RuntimeError(f'seed {seed}: round exceeded the {LIMIT}-frame limit')
            start = time.perf_counter()
            action = policy.action(features, mask)
            latency.append(time.perf_counter()-start)
            if trace is not None and decisions < 600:
                trace.append({'frame': int(info[1]), 'action': int(action),
                              'observation_sha256': hashlib.sha256(features.tobytes()).hexdigest()[:16],
                              **{name: [round(float(x), 4) for x in features[a:b]] for name, (a, b) in CHANNELS.items()}})
            if lib.kf60_play_step(handle, action, NEUTRAL) != 1:
                illegal += 1
                break
            decisions += 1
            read()
        return {'seed': seed, 'outcome': OUTCOMES.get(int(info[2]), 'invalid'), 'frames': int(info[1]),
                'decisions': decisions, 'illegal_actions': illegal, 'shots': int(info[4]), 'hits': int(info[5]),
                'decision_ms_mean': round(1000*float(np.mean(latency)), 3) if latency else None,
                'decision_ms_p95': round(1000*float(np.percentile(latency, 95)), 3) if latency else None}
    finally:
        lib.kf60_play_free(handle)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--seeds', type=int, nargs='*', default=[])
    parser.add_argument('--suite', type=Path, help='frozen suite JSON; its seeds replace --seeds')
    parser.add_argument('--model', type=Path, help='model manifest (default: tank_game/models/active.json)')
    parser.add_argument('--trace', type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    seeds = json.loads(args.suite.read_text())['seeds'] if args.suite else args.seeds
    if not seeds:
        parser.error('give --seeds or --suite')
    policy, lib, trace = load_hybrid(args.model, fallback=False), bridge(), [] if args.trace else None
    rounds = [play_round(lib, policy, s, trace if i == 0 else None) for i, s in enumerate(seeds)]
    tally = {k: sum(r['outcome'] == k for r in rounds) for k in OUTCOMES.values()}
    report = {'model': policy.label, 'model_sha256': policy.manifest['sha256'], 'opponent': 'native Laika',
              'suite': str(args.suite) if args.suite else None, 'rounds': len(rounds), 'tally': tally,
              'illegal_actions': sum(r['illegal_actions'] for r in rounds),
              'llm_calls': 0, 'tokens': 'N/A (local NumPy inference)', 'cost_usd': 0.0, 'per_round': rounds}
    print(json.dumps({k: v for k, v in report.items() if k != 'per_round'}, indent=2))
    for path, data in ((args.out, report), (args.trace, trace)):
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=1) if path.suffix == '.json'
                            else ''.join(json.dumps(row)+'\n' for row in data))


if __name__ == '__main__':
    main()
