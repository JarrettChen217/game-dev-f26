# Evaluation

> Status (2026-10-31): the held-out suite is declared and frozen in
> [`eval/heldout-suite-v1.json`](eval/heldout-suite-v1.json). It has **not been run yet**. The numbers in
> section 2 are earlier *development* panels, not held-out results.

## 1. Question and design choices

**Question.** Can a small learned policy, given only on-screen facts, beat the strongest scripted opponent available
(native Laika) in a faithful reconstruction? And how does it compare with our simpler bots?

| Choice | Alternative it beat | Why |
| --- | --- | --- |
| Learned PPO policy as the model-driven player | Live LLM player (planned on 10-22, not built) | A duel needs one decision every 16.7 ms. LLM latency and cost per decision do not fit, and image or text summaries lose ballistic detail. The route change was discussed with the instructor at the Oct 27 office hour, who accepted a local model. The live-provider, token and cost fields are therefore N/A or 0 |
| 60 Hz engine, speeds rescaled from the 25 Hz reference | Running the reference at 25 Hz | 60 Hz matches the original's feel. Rescaling by 25/60 keeps distance per second, and `tests/laika_60hz_core.rs` checks that |
| 18 discrete actions (throttle × turn × fire) | Continuous control; a separate aim action | They cover every keyboard state a human can press. Aiming is learned by turning, as for a human |
| Facts-only observation (no seed, no opponent buttons, no planner state) | Feeding privileged state | A policy that reads hidden state would not transfer to a human opponent. Enforced by `tests/information_boundary.rs` |
| Native Laika as the main baseline | Only our Simple/Hard bots | Laika is a strong goal-stack planner from the reference, so beating it means more. Simple and Hard show the low end |

## 2. Development history (not held-out)

All of these are **repeated development panels**. The same seeds (21000–21099) were reused across checkpoints, so they
are not independent evidence and carry no significance claim. Opponent: native Laika. Player: argmax actions, one environment.

| Checkpoint | Win | Loss | Both destroyed | Time draw |
| --- | ---: | ---: | ---: | ---: |
| u5996 | 71 | 19 | 3 | 7 |
| u10092 | 67 | 25 | 4 | 4 |
| u14188 | 71 | 9 | 2 | 18 |
| u18284 | 93 | 2 | 4 | 1 |
| **u19588 (released)** | **89** | **6** | **3** | **2** |

How training worked:
- u19588 is a fixed time endpoint, not the best-scoring checkpoint. The rule was to stop at a frozen step or time cap and never choose by score.
- Training: PPO, fresh initialization, against native Laika.
- Scale: 16 workers × 16 environments × 308-step rollouts, 96,529,664 decisions in total, on a Linux RTX 3070 training machine.

## 3. Held-out comparison (frozen 2026-10-31, to run)

- Suite: [`eval/heldout-suite-v1.json`](eval/heldout-suite-v1.json).
- Seeds: 100 map seeds starting at 3,000,000,000. Every earlier panel used seeds below 100,000.
- Player: frozen u19588 (weights SHA-256 `c90d02c9…d191`).
- Opponents: native Laika, Hard and Simple.

The rules, fixed before any run:
- no training or tuning;
- each opponent is run once over all seeds;
- every round is reported.

Command (working directory `midterms/jarrettchen217`):

```bash
uv run --frozen python scripts/evaluate.py --suite eval/heldout-suite-v1.json --out eval/heldout-results-v1.json
```

| Opponent | Win | Loss | Both destroyed | Time draw | Illegal actions | Rounds at limit | Decision ms (mean / p95) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| native Laika | TODO | | | | | | |
| Hard | TODO | | | | | | |
| Simple | TODO | | | | | | |

LLM calls: 0 · tokens: N/A · cost: $0 (local NumPy inference). Run date and commit: TODO.

## 4. Smoke checks already run (2026-10-31)

- `scripts/evaluate.py --seeds 1000 1001`:
  - result: 1 win, 1 loss, 0 illegal actions;
  - this is a smoke test only, not evidence of strength.
- `scripts/run_checks.py`, all passing:
  - 5 Rust test binaries;
  - 496 Python tests;
  - one full u19588 round.

## 5. Limitations

- The learned player always sits in seat 0. The ABI has no seat swap, so side balance comes only from per-seed mazes and spawns.
- The engine is built for macOS arm64. Other platforms use the browser build.
- The training-environment digest pins the Rust sources u19588 was trained on.
  - Since then the play engine gained only `#[cfg(not(target_arch="wasm32"))]` guards (for the browser build).
  - Native behavior is unchanged, but the source hashes differ, so the training library is not shipped. `tank_game/laika_60hz/training/manifest.json` is kept as the record.
- Some older tests written for a retired 25 Hz research profile were not carried into this folder. The remaining tests all pass.
- Known behavior: u19588 sometimes oscillates between actions. This is visible in the trace and was left as trained.
