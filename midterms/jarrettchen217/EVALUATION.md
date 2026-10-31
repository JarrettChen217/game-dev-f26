# Evaluation

> Status (2026-10-31): the held-out suite was frozen in [`eval/heldout-suite-v1.json`](eval/heldout-suite-v1.json)
> (commit e58cc0b), then **run once** at commit 10ee4d5. Results are in section 3 and
> [`eval/heldout-results-v1.json`](eval/heldout-results-v1.json). Section 2 lists earlier *development* panels for context only.

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

## 3. Held-out comparison (frozen and run once, 2026-10-31)

The suite was frozen before the run:
- [`eval/heldout-suite-v1.json`](eval/heldout-suite-v1.json), committed in e58cc0b;
- seeds: 100 map seeds starting at 3,000,000,000, while every earlier panel used seeds below 100,000;
- player: frozen u19588 (weights SHA-256 `c90d02c9…d191`), argmax actions;
- opponents: native Laika, Hard and Simple.

The rules, fixed before the run:
- no training or tuning;
- each opponent is played once over all seeds;
- every round is reported.

The run:
- one run at commit `10ee4d5`, 2026-10-31 21:34–21:41 UTC;
- on the 14-inch MacBook Pro (M2 Pro);
- per-round results in [`eval/heldout-results-v1.json`](eval/heldout-results-v1.json).

```bash
# working directory: midterms/jarrettchen217
uv run --frozen python scripts/evaluate.py --suite eval/heldout-suite-v1.json --opponent all --out eval/heldout-results-v1.json
```

| Opponent | Win | Loss | Both destroyed | Time draw | Win rate (95% Wilson) | Illegal actions | Rounds at limit | Mean round length | Decision ms, mean / worst-round p95 |
| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | --- |
| native Laika | 96 | 1 | 1 | 2 | 96% (90.2–98.4) | 0 | 0 | 514 frames (8.6 s) | 0.24 / 1.25 |
| Hard | 78 | 9 | 5 | 8 | 78% (68.9–85.0) | 0 | 0 | 804 frames (13.4 s) | 0.26 / 0.53 |
| Simple | 78 | 2 | 2 | 18 | 78% (68.9–85.0) | 0 | 0 | 774 frames (12.9 s) | 0.23 / 0.37 |

LLM calls: 0 · tokens: N/A · cost: $0. Inference is local NumPy, under 1.3 ms per decision against a 16.7 ms frame.

How the opponents were driven:
- **Laika** runs inside the engine in seat 1.
- **Hard and Simple** drive seat 1 through the game's own public observation and request path, at the decision rate the game uses for them (10 per second).
- u19588 always plays seat 0.

**Reading the results.**
- u19588 beat all three opponents on maps it had never been checked on.
- Its strongest result is against native Laika, the opponent it was trained against: 96%, above the 89% on the reused development seeds. The intervals overlap, so this is not a claim that it improved.
- Against the scripted bots it wins less often, and most non-wins are different:
  - against Hard, more of them are losses and double kills, because Hard fires predictively;
  - against Simple, most are time draws (18 of 22): Simple wanders on a patrol route and rarely fires, and u19588 often does not chase it down within 30 s.
- This fits training against a single opponent. The policy learned to duel an aggressive planner, not to hunt a passive target.
- Sample trace of observation → action for the first 120 frames of seed 1000: [`eval/trace-seed1000-first120.jsonl`](eval/trace-seed1000-first120.jsonl). Each row has the observation channels, their hash and the chosen action.

## 4. Other checks run (2026-10-31)

- `scripts/run_checks.py`, all passing:
  - 5 Rust test binaries;
  - 496 Python tests;
  - one full u19588 round.
- The same checks pass in CI on the author's fork (macOS arm64).

## 5. Limitations

- One run of 100 seeds per opponent; the intervals above are the honest error bars.
- The learned player always sits in seat 0. The ABI has no seat swap, so side balance comes only from per-seed mazes and spawns.
- The engine is built for macOS arm64. Other platforms use the browser build.
- The training-environment digest pins the Rust sources u19588 was trained on.
  - Since then the play engine gained only `#[cfg(not(target_arch="wasm32"))]` guards (for the browser build).
  - Native behavior is unchanged, but the source hashes differ, so the training library is not shipped. `tank_game/laika_60hz/training/manifest.json` is kept as the record.
- Some older tests written for a retired 25 Hz research profile were not carried into this folder. The remaining tests all pass.
- Known behavior: u19588 sometimes oscillates between actions. This is visible in the trace and was left as trained.
