# Tank Trouble reconstruction with a learned player (u19588)

**Student:** jarrettchen217 · **Course:** COMS E6998 AI in Practice: Game Design and Development, Fall 2026 midterm

Two tanks duel in a random maze; bullets ricochet off walls, and a tank dies to any bullet, including its own.
This folder holds a 60 Hz reconstruction of the classic *Tank Trouble* duel, plus an agent that plays it:
**Hybrid u19588**, a small PPO policy we trained. It reads the same observation every round, returns one of 18 actions, and
runs locally with NumPy. It makes no LLM or network calls during play.

- Demo video (3–5 min): **TODO — link added before submission**
- Evaluation: [EVALUATION.md](EVALUATION.md) · Agent team: [AGENT-TEAM.md](AGENT-TEAM.md) · Peer notes: [peer-notes/](peer-notes/)
- Browser build of the same game, no install needed: https://jarrettchen217.github.io/tank-trouble-reconstruction/

## Scope

In scope:
- the two-tank duel: random maze, movement, ricochet bullets, 5-bullet magazine, round settlement, score;
- four opponents on one engine:
  - Simple and Hard (our scripted bots);
  - native Laika (the reference bot from the Killfield reconstruction);
  - Hybrid u19588 (learned).

Out of scope: power-up crates (the timer still runs, but crates never spawn in a duel), more than two tanks, online play.

An earlier course post named a different project for the midterm. The scope changed to this game.

## Setup

Requirements: **macOS on Apple silicon (arm64)**, [uv](https://docs.astral.sh/uv/), and `rustc` (only for checks and rebuilds; `brew install rust`). The prebuilt native
library in `tank_game/laika_60hz/play/` targets this platform. On other platforms, use the browser build above.

All commands below run from **`midterms/jarrettchen217/`** inside a clone of the course repository.

```bash
cd midterms/jarrettchen217
uv sync --frozen
```

## Play

| What | Command (working directory: `midterms/jarrettchen217`) |
| --- | --- |
| Menu: Bot on/off, Simple / Hard / Laika / Hybrid, fixed or random map, tutorial | `uv run --frozen python -B -m tank_game` |
| Straight into a duel against u19588 on a reproducible map | `uv run --frozen python -B -m tank_game --duel --strategy hybrid --random-map --map-seed 1000` |
| Print the public game state without a window | add `--inspect` to the duel command |

Controls: W/S or Up/Down drive, A/D or Left/Right turn, F or Space fires (release before firing again), Esc pauses.

## Test

| What | Command (working directory: `midterms/jarrettchen217`) |
| --- | --- |
| Every deterministic check, the same as CI | `uv run --frozen python scripts/run_checks.py` |
| Python tests only | `uv run --frozen python -m unittest discover -s tests` |
| Rebuild the native library from the Rust source | `uv run --frozen python scripts/build_native.py` |
| Lint | `uv run --frozen ruff check .` |

The CI workflow is `.github/workflows/midterm-jarrettchen217.yml` at the course-repository root. It runs on macOS arm64,
rebuilds the native library from source, then runs `scripts/run_checks.py`. The five check kinds:

| Kind | Where |
| --- | --- |
| Rules | `tests/laika_60hz_core.rs` (60 Hz movement, ballistics, time conservation), `tests/test_shooting.py`, `test_ricochets.py`, `test_tank_collision.py` |
| Legal and illegal actions | `tests/episode_contract.rs` (all 18 accepted; out-of-range rejected with no state change), `tests/test_controller_contract.py`, `tests/source60_play.rs` |
| Termination | `tests/episode_contract.rs` (terminal rounds stay terminal), `tests/test_round_lifecycle.py`, `tests/source60_training_core.rs` |
| Regression | `tests/episode_contract.rs` (pinned digest of a fixed opening; same seed and actions reproduce the round exactly), `tests/test_model_registry.py`, `test_world_regressions.py`, `test_edge_wall_regression.py` |
| Episode limits | `tests/episode_contract.rs` (a passive round ends as a time draw within 1800 + 300 frames), `tests/test_learning_environment.py` |
| Information boundary | `tests/information_boundary.rs` |

## Evaluate

| What | Command (working directory: `midterms/jarrettchen217`) |
| --- | --- |
| One headless round, u19588 against native Laika | `uv run --frozen python scripts/evaluate.py --seeds 1000` |
| Log observation → action for that round | add `--trace reports/trace.jsonl` |
| The frozen held-out suite | `uv run --frozen python scripts/evaluate.py --suite eval/heldout-suite-v1.json --out eval/heldout-results-v1.json` |
| A different model, without changing code | add `--model path/to/actor.json`, or set `TANK_HYBRID_MODEL` |

## The player's interface (five operations)

The learned player sees only what the play bridge hands it, and it can only answer with an action.
The engine (`tank_game/laika_60hz/training/source/`) owns all state.

| Operation | Equivalent here |
| --- | --- |
| `reset(seed)` | `Training::new(seed)` / `kf60_play_new(seed, …)`: new maze, spawns and history for that seed |
| `observe()` | `.observation`: 1028 float32 features (schema24) plus a 10-slot live-bullet mask, read with `kf60_play_read` |
| `legal_actions()` | always all 18: throttle {back, none, forward} × turn {left, none, right} × fire {no, yes}. A shot with an empty magazine or a held trigger is legal and just does nothing |
| `step(action)` | `kf60_play_step`: returns `1` if accepted and one 60 Hz frame advances, `-1` if out of range (nothing changes), `0` if the round is already over |
| `outcome()` | `info[2]`: 0 running, 1 win, 2 loss, 3 both destroyed, 4 time draw |

The model is chosen by a manifest, not by code. `tank_game/models/active.json` points to `u19588/actor.json`:
1 MB of inference-only float32 weights plus their SHA-256. Before play, `tank_game/models/registry.py` checks a
manifest against the game ABI in `tank_game/models/contract.py`: architecture, schema 24, 1028 inputs, 18 actions,
the training-environment digest, tensor shapes, and finite weights. If a swapped model is rejected, the game falls back to u19588 and labels it as a fallback.

## Information boundary

The observation encoder is `hybrid_obs.rs`. Its rule is to give facts about the board, never answers about the decision.

**It includes:**
- the maze grid (12 × 10 × 7 channels);
- 16 wall rays;
- own pose and the opponent's pose and velocity;
- BFS navigation;
- whether the current barrel angle has a clear shot, for both tanks;
- up to 10 bullets in flight, with their straight-line forecasts;
- threat counts;
- the round phase;
- its own last three actions, action-change rate and idle streak;
- a per-move survival outlook computed from visible bullets.

**It never includes:**
- the seed or RNG state;
- the opponent's buttons this frame (the policy sees motion, as a human would, not keystrokes);
- the opponent planner's internal goals or parameters;
- a sweep over turret angles.

`tests/information_boundary.rs` changes each hidden field in turn on a live round and requires the observation to stay
bit-identical. As a control, it also checks that moving the opponent does change the observation.
The player does not use repository tools, files or the network during play.

## Limits

- One round is at most **1800 task frames (30 s at 60 Hz) plus 300 grace frames**. After the first kill, the world keeps running for 300 frames, so residual bullets still count.
- The player makes one decision per frame. `scripts/evaluate.py` aborts a round that passes the limit and counts any rejected action.
- **Model calls:** local NumPy inference only, so there are 0 LLM calls, tokens are N/A and cost is $0. Decision latency is reported per round.

## Rule source map

Labels:
- **code**: taken from the Killfield source;
- **design**: our own decision;
- **observed**: matched to how the original plays;
- **assumed**: not confirmed.

| Rule | Value | Label | Location |
| --- | --- | --- | --- |
| Maze | Seeded grid, 4–12 × 4–10 cells | code | `tank_game/original_laika/source/maze.rs` |
| Clock | 60 frames/s. Every 25 Hz reference speed is rescaled by 25/60 so distance per second is unchanged | design | `tank_game/laika_60hz/source/constants.rs:9-11`, `tests/laika_60hz_core.rs` |
| Tank motion | Forward 4.0, back 2.5, turn 10° per reference step, 5 collision substeps | code (time-converted) | `constants.rs:56-59` |
| Bullets | Speed 4.5 per reference step, 10 s lifetime, ricochet off walls, 7 hit substeps | code | `constants.rs:20-22`, `original_laika/source/ballistics.rs` |
| Magazine | At most 5 own bullets alive | code | `constants.rs:51` |
| Firing | Edge-triggered: release before the next shot | code | `laika_60hz/source/game.rs` (`immediate_fire_tests`) |
| Friendly fire | Any bullet kills any tank, including its owner | code | `game.rs`, `tests/test_shooting.py` |
| Settlement | The world runs 300 frames after a kill and freezes 120 frames before reset | code | `constants.rs:36-42` |
| Outcomes | Win / loss / both destroyed / time draw | design | `training/source/lib.rs` (`step`) |
| Time limit | 1800 frames, plus 300 grace if a kill is settling | design | `training/source/duel.rs:3-4` |
| Crates | Never spawn in a duel | design | `game.rs` (`crate_timer`) |
| Action set | 18 discrete actions | design | `training/source/score.rs` (`CANDIDATES`) |
| Laika opponent | Goal-stack planner | code | `laika_60hz/source/laika.rs` |
| Simple / Hard opponents | Scripted bots | design | `tank_game/strategies.py`, `tank_game/controllers.py` |

## Sources, licenses and what is ours

- **Killfield** (Cichlider/killfield, MIT; notice in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and in each
  adapted folder's `LICENSE`). Killfield is itself a reconstruction of Tank Trouble.
  - We adapted: the Rust engine (maze, ballistics, game loop), the Laika bot, the schema24 observation encoder, and the PPO trainer design.
  - `tank_game/original_laika/engine.wasm` is the author's unchanged 25 Hz build. It is used only by the optional `--rules-profile laika-original` comparison.
- **Ours:**
  - the 60 Hz conversion and its tests;
  - the Pyxel game, menu, HUD and tutorial;
  - the Simple and Hard bots;
  - the model registry and contract checks;
  - all training runs.
- **The u19588 weights are ours.** We trained them with PPO from a fresh initialization on the 60 Hz environment, against native Laika, on a Linux RTX 3070 training machine. Training ran as a pilot, then continuations, ending at PPO update 19588. No earlier or third-party weights were used.
  - Only the 1 MB inference tensors are published here; no checkpoint, optimizer state or training log.
  - An earlier development build used the Killfield author's own trained model. It is not part of this submission.
- **AI use:** the code was written with Codex and Claude Code agents under the student's direction (see [AGENT-TEAM.md](AGENT-TEAM.md)).

## Folder map

- `tank_game/`: the game (Python/Pyxel front end, Rust native60Hz engine, model registry, bots).
- `research/killfield/tank_transfer/actor.py`: the NumPy forward pass used by the learned player.
- `tests/`: Python and Rust tests.
- `scripts/`: `run_checks.py`, `evaluate.py`, `build_native.py`.
- `eval/`: the frozen held-out suite and, once run, its results.
- `peer-notes/`: playtest notes given and received.
