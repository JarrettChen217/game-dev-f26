//!Source60 adaptation of the verified schema24 reconstruction; see reference-sources.json.
//! Original schema24 encoder from Cichlider/killfield 5912a1ace3099ac51069e8a5684f1090ae6538c8.
//! Original source SHA256 7dff97b0935ee2f584c24b050e58f7026fea644751a574fc546c34ef569a1ce9.
//! Tests requiring unpublished DuelState history were not copied. Our dodge helper is below.
//! Observation for the duel curriculum: everything a player could work out,
//! and nothing they could not.
//!
//! The range curriculum spent 100 dimensions and deliberately withheld the
//! maze, on the strength of one bad experiment with a CNN map head. This one
//! goes the other way, because the reward went the other way: with nothing but
//! a win/loss at the end there is no shaping term left to carry information,
//! so the information has to be in here. That matches the project's own record
//! anyway — two observation channels bought more than the entire reward-shaping
//! phase did.
//!
//! # The line
//!
//! **Facts about the world, never answers about the decision.** Concretely,
//! four things are refused:
//!
//! * **Seed and RNG state.** Not available at deployment; a policy that used
//!   them would not survive leaving the trainer.
//! * **The opponent's internal goal stack.** Laika's `Goal`, the planner's
//!   commitments. Opponent-specific, so it evaporates when the opponent
//!   changes, and a policy leaning on it never learned to read the board.
//! * **The opponent's current buttons.** These look observable — the planner's
//!   `L1` model reads them — but that is a same-frame privileged peek. A human
//!   sees motion, not keystrokes, so motion is what goes in: velocity and
//!   angular velocity, differenced from where things were last frame.
//! * **A turret sweep.** `check_bullet_path` accepts any angle, so scanning 36
//!   of them is mechanically trivial and would hand over the best firing
//!   angle. Only the *current* angle is probed, for both tanks. Finding a
//!   firing position still has to be learned by turning.
//!
//! What is given freely is any deterministic function of what is on screen:
//! wall layout, BFS distances, dead ends, the ballistics of bullets already in
//! flight. Precomputing those is not cheating; they are consequences of the
//! visible state, and a good player computes them too.
//!
//! # The two approximations, stated
//!
//! Both aim assist and the per-bullet forecast simulate forward assuming the
//! tanks hold still. Bullets only interact with walls, so the geometry is
//! exact; what is approximate is that a target can move out of the way. The
//! channels answer "where does this go if nobody moves", not "what will
//! happen".

use crate::constants as C;
use crate::duel::DUEL_FRAMES;
use crate::game::Game;
use crate::risk::{incoming_risk, reflective_closest};

// ---------------------------------------------------------------- layout

/// The engine draws mazes from 4..12 by 4..10, so this covers every arena the
/// generator can produce, with a validity channel for the padding.
pub const MAP_W: usize = 12;
pub const MAP_H: usize = 10;
pub const MAP_CHANNELS: usize = 7;
pub const MAP_DIM: usize = MAP_W * MAP_H * MAP_CHANNELS;

pub const RAY_COUNT: usize = 16;
pub const SELF_DIM: usize = 12;
pub const OPPONENT_DIM: usize = 12;
pub const NAV_DIM: usize = 10;
pub const AIM_DIM: usize = 5;
pub const BULLET_SLOTS: usize = 10;
pub const BULLET_DIM: usize = 10;
pub const THREAT_DIM: usize = 3;
pub const PHASE_DIM: usize = 4;
pub const LAST_ACTION_DIM: usize = 3;
/// How many live bullets (mine or theirs) are on a course to hit me right
/// now — a count, not the worst-case urgency `THREAT_OFFSET` already carries.
/// Tacked on after everything else so widening a trained checkpoint to this
/// schema is a pure append, not a reshuffle: see `training/widen_obs.py`.
pub const SELF_THREAT_COUNT_DIM: usize = 1;

/// How many past frames of the reading seat's own action are given, counting
/// the previous frame. Frame `t-1` keeps its original home at
/// `LAST_ACTION_OFFSET`; the older ones live in the appended block, so every
/// pre-existing channel keeps the index it had.
pub const ACTION_HISTORY_DEPTH: usize = 3;
pub const OLDER_ACTIONS_DIM: usize = (ACTION_HISTORY_DEPTH - 1) * LAST_ACTION_DIM;
/// The round's action-change rate *so far*. `duel::style_bonus` grades exactly
/// this ratio at the end of the round, and a policy graded on an accumulator
/// it cannot see can only learn a blanket "change less often" prior — never
/// "I have spent my budget, tighten up". So it goes in.
pub const CHANGE_RATE_DIM: usize = 1;
/// Per-movement survival outlook from `score::dodge_safety`, one value for
/// each `[throttle, turn]` pair.  This remains part of the observation so the
/// shared representation and critic can see which safe continuations exist;
/// the actor also receives the same values through an explicitly aligned
/// logit shortcut.
pub const DODGE_DIM: usize = 9;
/// Consecutive frames on which this seat selected the fully neutral movement
/// (with or without firing), clipped and normalised by
/// `IDLE_STREAK_CAP_FRAMES`.  This is a fact about recent behaviour; the
/// actor decides how strongly to dislike a long streak.
pub const IDLE_STREAK_DIM: usize = 1;
pub const IDLE_STREAK_CAP_FRAMES: u32 = 60;

pub const MAP_OFFSET: usize = 0;
pub const RAY_OFFSET: usize = MAP_OFFSET + MAP_DIM;
pub const SELF_OFFSET: usize = RAY_OFFSET + RAY_COUNT;
pub const OPPONENT_OFFSET: usize = SELF_OFFSET + SELF_DIM;
pub const NAV_OFFSET: usize = OPPONENT_OFFSET + OPPONENT_DIM;
pub const AIM_SELF_OFFSET: usize = NAV_OFFSET + NAV_DIM;
pub const AIM_OPPONENT_OFFSET: usize = AIM_SELF_OFFSET + AIM_DIM;
pub const BULLET_OFFSET: usize = AIM_OPPONENT_OFFSET + AIM_DIM;
pub const THREAT_OFFSET: usize = BULLET_OFFSET + BULLET_SLOTS * BULLET_DIM;
pub const PHASE_OFFSET: usize = THREAT_OFFSET + THREAT_DIM;
pub const LAST_ACTION_OFFSET: usize = PHASE_OFFSET + PHASE_DIM;
pub const SELF_THREAT_COUNT_OFFSET: usize = LAST_ACTION_OFFSET + LAST_ACTION_DIM;
pub const OLDER_ACTIONS_OFFSET: usize = SELF_THREAT_COUNT_OFFSET + SELF_THREAT_COUNT_DIM;
pub const CHANGE_RATE_OFFSET: usize = OLDER_ACTIONS_OFFSET + OLDER_ACTIONS_DIM;
pub const DODGE_OFFSET: usize = CHANGE_RATE_OFFSET + CHANGE_RATE_DIM;
pub const IDLE_STREAK_OFFSET: usize = DODGE_OFFSET + DODGE_DIM;
pub const OBS_DIM: usize = IDLE_STREAK_OFFSET + IDLE_STREAK_DIM;

/// Bumped whenever any of the above changes. The trainer stamps it into every
/// checkpoint manifest and the viewer refuses a model that disagrees, so a
/// layout change can never silently drive an old policy.
pub const OBS_SCHEMA_VERSION: u32 = 24;

// ------------------------------------------------------------- normalisers

/// How far a wall ray looks, in cells.
const RAY_CELLS: f64 = 4.0;
/// Steps per cell while marching. The wall grid answers point queries only, so
/// this is the ray's accuracy.
const RAY_STEPS_PER_CELL: usize = 8;
/// Path lengths divide by this and clip. The largest arena is 12x10, whose
/// longest corridor-following path is comfortably inside it.
const MAX_PATH_CELLS: f64 = 60.0;
/// Bullet speeds divide by this multiple of a cell per frame.
const MAX_BULLET_SPEED_CELLS: f64 = 0.5;
/// How far ahead a bullet is flown to decide whether it is coming for someone.
const FORECAST_FRAMES: f64 = 180.0;
const FORECAST_BOUNCES: i32 = 2;
/// Cells. The same effective tank size `risk.rs` uses internally.
const HIT_RADIUS_CELLS: f64 = 0.25;

/// What the seat reading this observation has been doing lately.
///
/// Per seat rather than per round: the frozen pool opponent is the same
/// network reading from the other chair, so "my last action" and "how twitchy
/// I have been" have to mean *its* actions when it is the one looking. The
/// round's own bookkeeping lives in `duel::DuelState`, which hands one of
/// these out for each seat.
#[derive(Clone, Copy, Debug)]
pub struct SeatHistory {
    /// `actions[0]` is the previous frame, `actions[1]` the frame before it.
    /// `None` where the round is still too young to have one.
    pub actions: [Option<u16>; ACTION_HISTORY_DEPTH],
    /// Frames that chose a different action than the frame before them.
    pub changes: u32,
    /// Frames played so far this round.
    pub frames: u32,
    /// Consecutive actions whose movement component was fully neutral. Fire
    /// does not reset it: `[neutral, neutral, fire]` still stands still.
    pub idle_streak: u32,
}

impl Default for SeatHistory {
    fn default() -> Self {
        Self { actions: [None; ACTION_HISTORY_DEPTH], changes: 0, frames: 0, idle_streak: 0 }
    }
}

impl SeatHistory {
    /// Push this frame's action, ageing the rest and counting a change.
    pub fn record(&mut self, action: u16) {
        if self.actions[0].is_some_and(|previous| previous != action) {
            self.changes += 1;
        }
        for i in (1..ACTION_HISTORY_DEPTH).rev() {
            self.actions[i] = self.actions[i - 1];
        }
        self.actions[0] = Some(action);
        self.frames += 1; // Reference FFI omitted this; real history must count steps.
        let candidate = crate::score::CANDIDATES
            [(action as usize).min(crate::score::CANDIDATES.len() - 1)];
        if candidate[0] == 1 && candidate[1] == 1 {
            self.idle_streak = self.idle_streak.saturating_add(1);
        } else {
            self.idle_streak = 0;
        }
    }

    /// Changes per frame so far, in `[0, 1]`. Zero for a round too young to
    /// have had the chance to change anything.
    pub fn change_rate(&self) -> f32 {
        if self.frames < 2 {
            return 0.0;
        }
        (self.changes as f32 / ((self.frames - 1) as f32 * C::STEP_25 as f32)).clamp(0.0, 1.0)
    }
}

pub struct DuelObservation {
    pub values: [f32; OBS_DIM],
    pub bullet_mask: [bool; BULLET_SLOTS],
}

impl Default for DuelObservation {
    fn default() -> Self {
        Self { values: [0.0; OBS_DIM], bullet_mask: [false; BULLET_SLOTS] }
    }
}

// ------------------------------------------------------------------ helpers

/// Rotate a world vector into a tank's frame: `+x` ahead, `+y` to its left.
fn to_own_frame(rotation: f64, dx: f64, dy: f64) -> (f64, f64) {
    let facing = (rotation - 90.0) * C::DEG;
    let (sin, cos) = facing.sin_cos();
    (dx * cos + dy * sin, -dx * sin + dy * cos)
}

/// Distance to the first wall along `angle`, in cells, capped at `RAY_CELLS`.
fn wall_ray(game: &Game, x: f64, y: f64, angle: f64) -> f64 {
    let (sin, cos) = angle.sin_cos();
    let steps = (RAY_CELLS * RAY_STEPS_PER_CELL as f64) as usize;
    let step = game.scale / RAY_STEPS_PER_CELL as f64;
    for i in 1..=steps {
        let travelled = step * i as f64;
        if game.wall_grid.hit(x + cos * travelled, y + sin * travelled) {
            return travelled / game.scale;
        }
    }
    RAY_CELLS
}

fn cell_of(game: &Game, tank: usize) -> (i64, i64) {
    let (x, y) = (game.tanks[tank].x, game.tanks[tank].y);
    (
        (x / game.scale).floor().max(0.0) as i64,
        (y / game.scale).floor().max(0.0) as i64,
    )
}

/// BFS distance in cells from `from`'s cell to `to`'s cell, if reachable.
fn path_cells(game: &Game, from: (i64, i64), to: (i64, i64)) -> Option<f64> {
    if to.0 < 0 || to.1 < 0 {
        return None;
    }
    let (tx, ty) = (to.0 as usize, to.1 as usize);
    if tx >= game.maze.w || ty >= game.maze.h {
        return None;
    }
    game.dist_map(from.0, from.1)
        .map(|d| d[tx * game.maze.h + ty])
        .filter(|v| v.is_finite())
}

fn dead_end_at(game: &Game, cell: (i64, i64)) -> f64 {
    if cell.0 < 0 || cell.1 < 0 {
        return 0.0;
    }
    let (x, y) = (cell.0 as usize, cell.1 as usize);
    if x >= game.maze.w || y >= game.maze.h {
        return 0.0;
    }
    let v = game.dead_ends[x * game.maze.h + y];
    if v.is_finite() { v } else { C::MAXDEADENDPENALTY }
}

/// Angular difference between two headings in degrees, in `(-180, 180]`.
fn turn_rate(current: f64, previous: f64) -> f64 {
    crate::game::norm_rot(current - previous)
}

/// `[hits_enemy, hits_self, hits_nothing, time_to_hit, closest_pass]` for the
/// angle a tank's barrel is at right now. Nothing about any other angle.
fn aim_assist(game: &Game, tank: usize) -> [f32; AIM_DIM] {
    let mut out = [0.0f32; AIM_DIM];
    if !game.tanks[tank].alive {
        out[2] = 1.0;
        return out;
    }
    let result = crate::ballistics::check_bullet_path(
        game,
        tank,
        game.tanks[tank].rotation,
        2.0 * game.scale,
        2.0,
    );
    out[match result.outcome {
        crate::ballistics::ShotOutcome::Hit => 0,
        crate::ballistics::ShotOutcome::Suicide => 1,
        crate::ballistics::ShotOutcome::Nothing => 2,
    }] = 1.0;
    out[3] = (result.time / C::BULLETLIFETIME as f64).clamp(0.0, 1.0) as f32;
    out[4] = (result.closest / (C::MOVIEWIDTH + C::MOVIEHEIGHT)).clamp(0.0, 1.0) as f32;
    out
}

// ------------------------------------------------------------------- encode

/// Encode the duel observation for `tank` (always 0 in this curriculum).
///
/// `prev_pose` is `[x, y, rotation]` per tank as of the end of the previous
/// frame; `boxes` are the round's inflated wall rectangles. Both come from
/// `DuelState`, which owns the cross-frame memory so this stays a pure
/// function of the arguments.
pub fn encode(
    game: &Game,
    tank: usize,
    prev_pose: &[[f64; 3]; 2],
    boxes: &[[f64; 4]],
    history: &SeatHistory,
    out: &mut DuelObservation,
) {
    out.values = [0.0; OBS_DIM];
    out.bullet_mask = [false; BULLET_SLOTS];

    let other = 1 - tank;
    let me = game.tanks[tank];
    let them = game.tanks[other];
    let scale = game.scale;
    let width = game.maze.w as f64 * scale;
    let height = game.maze.h as f64 * scale;
    let span = width + height;
    let facing = (me.rotation - 90.0) * C::DEG;
    let v = &mut out.values;

    // --- maze grid, padded to the generator's largest arena ---------------
    let my_cell = cell_of(game, tank);
    let their_cell = cell_of(game, other);
    for x in 0..game.maze.w.min(MAP_W) {
        for y in 0..game.maze.h.min(MAP_H) {
            let base = MAP_OFFSET + (x * MAP_H + y) * MAP_CHANNELS;
            let (ix, iy) = (x as i64, y as i64);
            v[base] = 1.0; // this cell exists
            v[base + 1] = !game.maze.h_open(ix, iy - 1) as u8 as f32; // top
            v[base + 2] = !game.maze.v_open(ix + 1, iy) as u8 as f32; // right
            v[base + 3] = !game.maze.h_open(ix, iy) as u8 as f32; // bottom
            v[base + 4] = !game.maze.v_open(ix, iy) as u8 as f32; // left
            v[base + 5] = (my_cell == (ix, iy)) as u8 as f32;
            v[base + 6] = (their_cell == (ix, iy) && them.alive) as u8 as f32;
        }
    }

    // --- wall rays, evenly spaced around the hull -------------------------
    for i in 0..RAY_COUNT {
        let angle = facing + std::f64::consts::TAU * i as f64 / RAY_COUNT as f64;
        v[RAY_OFFSET + i] = (wall_ray(game, me.x, me.y, angle) / RAY_CELLS) as f32;
    }

    // --- self --------------------------------------------------------------
    let my_step = (me.x - prev_pose[tank][0], me.y - prev_pose[tank][1]);
    let (my_ahead, my_left) = to_own_frame(me.rotation, my_step.0, my_step.1);
    let speed_scale = MAX_BULLET_SPEED_CELLS * scale * C::STEP_25;
    let max_slots = game.settings_max_bullets.max(1) as f64;
    v[SELF_OFFSET] = (me.x / width).clamp(0.0, 1.0) as f32;
    v[SELF_OFFSET + 1] = (me.y / height).clamp(0.0, 1.0) as f32;
    v[SELF_OFFSET + 2] = facing.cos() as f32;
    v[SELF_OFFSET + 3] = facing.sin() as f32;
    v[SELF_OFFSET + 4] = (my_ahead / speed_scale).clamp(-1.0, 1.0) as f32;
    v[SELF_OFFSET + 5] = (my_left / speed_scale).clamp(-1.0, 1.0) as f32;
    v[SELF_OFFSET + 6] =
        (turn_rate(me.rotation, prev_pose[tank][2]) / C::TANK_TURN_SPEED).clamp(-1.0, 1.0) as f32;
    v[SELF_OFFSET + 7] =
        ((game.settings_max_bullets - me.bullets_fired).max(0) as f64 / max_slots) as f32;
    v[SELF_OFFSET + 8] = game.weapon_ready(tank) as u8 as f32;
    v[SELF_OFFSET + 9] = me.alive as u8 as f32;
    v[SELF_OFFSET + 10] = me.hit_something as u8 as f32;
    v[SELF_OFFSET + 11] = me.wall_sliding as u8 as f32;

    // --- opponent, entirely in my frame ------------------------------------
    let (rel_ahead, rel_left) = to_own_frame(me.rotation, them.x - me.x, them.y - me.y);
    let their_step = (them.x - prev_pose[other][0], them.y - prev_pose[other][1]);
    let (their_ahead, their_left) = to_own_frame(me.rotation, their_step.0, their_step.1);
    // Their heading relative to mine: 0 degrees means they face the way I do.
    let relative_heading = (them.rotation - me.rotation) * C::DEG;
    v[OPPONENT_OFFSET] = (rel_ahead / span).clamp(-1.0, 1.0) as f32;
    v[OPPONENT_OFFSET + 1] = (rel_left / span).clamp(-1.0, 1.0) as f32;
    v[OPPONENT_OFFSET + 2] = relative_heading.cos() as f32;
    v[OPPONENT_OFFSET + 3] = relative_heading.sin() as f32;
    v[OPPONENT_OFFSET + 4] = (their_ahead / speed_scale).clamp(-1.0, 1.0) as f32;
    v[OPPONENT_OFFSET + 5] = (their_left / speed_scale).clamp(-1.0, 1.0) as f32;
    v[OPPONENT_OFFSET + 6] = (turn_rate(them.rotation, prev_pose[other][2])
        / C::TANK_TURN_SPEED)
        .clamp(-1.0, 1.0) as f32;
    v[OPPONENT_OFFSET + 7] =
        ((game.settings_max_bullets - them.bullets_fired).max(0) as f64 / max_slots) as f32;
    v[OPPONENT_OFFSET + 8] = game.weapon_ready(other) as u8 as f32;
    v[OPPONENT_OFFSET + 9] = them.alive as u8 as f32;
    v[OPPONENT_OFFSET + 10] = them.hit_something as u8 as f32;
    v[OPPONENT_OFFSET + 11] = them.wall_sliding as u8 as f32;

    // --- navigation ---------------------------------------------------------
    match path_cells(game, my_cell, their_cell) {
        Some(cells) => v[NAV_OFFSET] = (cells / MAX_PATH_CELLS).clamp(0.0, 1.0) as f32,
        None => v[NAV_OFFSET] = 1.0,
    }
    // Which way to step to get closer, as a one-hot in my own frame. The BFS
    // grid is the shortest-path answer for *movement*, which is a fact about
    // the maze, not a recommendation about what to do this frame.
    if let Some(here) = path_cells(game, my_cell, their_cell) {
        let mut best: Option<(f64, usize)> = None;
        // World directions, then folded into my frame below.
        let steps: [(i64, i64, f64, f64); 4] = [
            (0, -1, 0.0, -1.0),
            (1, 0, 1.0, 0.0),
            (0, 1, 0.0, 1.0),
            (-1, 0, -1.0, 0.0),
        ];
        for &(dx, dy, wx, wy) in &steps {
            let neighbour = (my_cell.0 + dx, my_cell.1 + dy);
            let open = match (dx, dy) {
                (0, -1) => game.maze.h_open(my_cell.0, my_cell.1 - 1),
                (1, 0) => game.maze.v_open(my_cell.0 + 1, my_cell.1),
                (0, 1) => game.maze.h_open(my_cell.0, my_cell.1),
                _ => game.maze.v_open(my_cell.0, my_cell.1),
            };
            if !open {
                continue;
            }
            if let Some(there) = path_cells(game, neighbour, their_cell) {
                if there < here && best.map_or(true, |(b, _)| there < b) {
                    // Fold the world direction into my frame and bucket it.
                    let (ahead, left) = to_own_frame(me.rotation, wx, wy);
                    let quadrant = if ahead.abs() >= left.abs() {
                        if ahead > 0.0 { 0 } else { 2 }
                    } else if left > 0.0 {
                        1
                    } else {
                        3
                    };
                    best = Some((there, quadrant));
                }
            }
        }
        if let Some((_, quadrant)) = best {
            v[NAV_OFFSET + 1 + quadrant] = 1.0;
        }
    }
    let straight = rel_ahead.hypot(rel_left);
    v[NAV_OFFSET + 5] = (straight / span).clamp(0.0, 1.0) as f32;
    if straight > 1e-9 {
        v[NAV_OFFSET + 6] = (rel_ahead / straight) as f32;
        v[NAV_OFFSET + 7] = (rel_left / straight) as f32;
    }
    v[NAV_OFFSET + 8] = (dead_end_at(game, my_cell) / C::MAXDEADENDPENALTY) as f32;
    v[NAV_OFFSET + 9] = (dead_end_at(game, their_cell) / C::MAXDEADENDPENALTY) as f32;

    // --- aim assist, mine and theirs ---------------------------------------
    v[AIM_SELF_OFFSET..AIM_SELF_OFFSET + AIM_DIM].copy_from_slice(&aim_assist(game, tank));
    v[AIM_OPPONENT_OFFSET..AIM_OPPONENT_OFFSET + AIM_DIM]
        .copy_from_slice(&aim_assist(game, other));

    // --- every live bullet --------------------------------------------------
    // Both tanks hold five, so ten slots is exact: nothing to prioritise and
    // nothing to truncate.
    let hit_radius = HIT_RADIUS_CELLS * scale;
    let mut worst_pass = 1.0f32;
    for (slot, bullet) in game
        .bullets
        .iter()
        .filter(|b| !b.removed)
        .take(BULLET_SLOTS)
        .enumerate()
    {
        let base = BULLET_OFFSET + slot * BULLET_DIM;
        let (ahead, left) = to_own_frame(me.rotation, bullet.x - me.x, bullet.y - me.y);
        let (vx, vy) = to_own_frame(me.rotation, bullet.x_speed, bullet.y_speed);
        let mine = bullet.owner == tank;
        v[base] = (ahead / span).clamp(-1.0, 1.0) as f32;
        v[base + 1] = (left / span).clamp(-1.0, 1.0) as f32;
        v[base + 2] = (vx / speed_scale).clamp(-1.0, 1.0) as f32;
        v[base + 3] = (vy / speed_scale).clamp(-1.0, 1.0) as f32;
        v[base + 4] = mine as u8 as f32;
        v[base + 5] = bullet.has_bounced as u8 as f32;
        v[base + 6] = (bullet.lifetime as f64 / C::BULLETLIFETIME as f64).clamp(0.0, 1.0) as f32;

        // Where this thing is going. A bullet only interacts with walls, so
        // the flight path is exact; what it assumes is that the tanks hold
        // still. My own un-bounced round cannot hurt me, which is the engine's
        // actual rule and not an approximation.
        let speed = bullet.x_speed.hypot(bullet.y_speed);
        if speed > 1e-9 {
            let harmless_to_me = mine && !bullet.has_bounced;
            if !harmless_to_me {
                let approach = reflective_closest(
                    bullet.x,
                    bullet.y,
                    bullet.x_speed / speed,
                    bullet.y_speed / speed,
                    speed,
                    FORECAST_FRAMES,
                    FORECAST_BOUNCES,
                    boxes,
                    me.x,
                    me.y,
                );
                if approach.distance <= hit_radius {
                    v[base + 7] = 1.0;
                    v[base + 9] = (approach.frame / FORECAST_FRAMES).clamp(0.0, 1.0) as f32;
                } else {
                    v[base + 9] = 1.0;
                }
                worst_pass = worst_pass.min((approach.distance / (2.0 * scale)).min(1.0) as f32);
            } else {
                v[base + 9] = 1.0;
            }

            let harmless_to_them = !mine && !bullet.has_bounced;
            if !harmless_to_them && them.alive {
                let approach = reflective_closest(
                    bullet.x,
                    bullet.y,
                    bullet.x_speed / speed,
                    bullet.y_speed / speed,
                    speed,
                    FORECAST_FRAMES,
                    FORECAST_BOUNCES,
                    boxes,
                    them.x,
                    them.y,
                );
                v[base + 8] = (approach.distance <= hit_radius) as u8 as f32;
            }
        } else {
            v[base + 9] = 1.0;
        }
        out.bullet_mask[slot] = true;
    }

    // --- threat summary ------------------------------------------------------
    v[THREAT_OFFSET] = incoming_risk(game, boxes, tank).clamp(0.0, 1.0) as f32;
    v[THREAT_OFFSET + 1] = incoming_risk(game, boxes, other).clamp(0.0, 1.0) as f32;
    v[THREAT_OFFSET + 2] = worst_pass;

    // How many of the slots just filled in above are flagged "reaches me"
    // (`base + 7`, set a few lines up). A count, where THREAT_OFFSET already
    // gave the worst-case urgency; the two are deliberately not merged.
    let self_threat_count = (0..BULLET_SLOTS)
        .filter(|&slot| out.bullet_mask[slot] && v[BULLET_OFFSET + slot * BULLET_DIM + 7] > 0.5)
        .count();
    v[SELF_THREAT_COUNT_OFFSET] =
        (self_threat_count as f32 / BULLET_SLOTS as f32).clamp(0.0, 1.0);

    // --- round phase and clock -----------------------------------------------
    // Settling means somebody has died and the world is still running out the
    // settlement window. `frozen` is the scoring freeze that follows it.
    //
    // This keys on `alive_count`, not `end_count >= 0`. Training builds one
    // fresh Game per episode, where `end_count` starts at -1 and only leaves it
    // in `destroy_tank` — which decrements `alive_count` in the same call, so
    // the two agree everywhere the trained policy ever looked. A Game that
    // plays round after round on one handle does not: `setup_battle`'s caller
    // re-arms `end_count` to a positive value for the new round, which would
    // otherwise report "settling" for every round after the first.
    let settling = game.alive_count <= 1 && !game.frozen;
    v[PHASE_OFFSET] = (!settling && !game.frozen) as u8 as f32;
    v[PHASE_OFFSET + 1] = settling as u8 as f32;
    v[PHASE_OFFSET + 2] = game.frozen as u8 as f32;
    let elapsed = (game.frame - game.round_start_frame).max(0) as f64;
    v[PHASE_OFFSET + 3] = (elapsed / DUEL_FRAMES as f64).clamp(0.0, 1.0) as f32;

    // --- what I have been doing ----------------------------------------------
    // Frame t-1 stays at its original offset; t-2 and older sit in the
    // appended block, so no pre-existing channel moves.
    for (age, action) in history.actions.iter().enumerate() {
        let Some(action) = *action else { continue };
        let a = crate::score::CANDIDATES[(action as usize).min(crate::duel::DUEL_ACTIONS - 1)];
        let base = if age == 0 {
            LAST_ACTION_OFFSET
        } else {
            OLDER_ACTIONS_OFFSET + (age - 1) * LAST_ACTION_DIM
        };
        v[base] = a[0] as f32 / 2.0;
        v[base + 1] = a[1] as f32 / 2.0;
        v[base + 2] = a[2] as f32;
    }

    // --- how twitchy this round has been so far ------------------------------
    v[CHANGE_RATE_OFFSET] = history.change_rate();
    v[IDLE_STREAK_OFFSET] =
        (history.idle_streak.min(IDLE_STREAK_CAP_FRAMES) as f32
            / IDLE_STREAK_CAP_FRAMES as f32)
            .clamp(0.0, 1.0);
}


/// RECONSTRUCTED, not the missing author's `score::dodge_safety`:
/// Existing projectiles only; hold each no-fire move for58native60Hz frames (~0.96s),
/// freeze opponent controls (no internal goal/RNG), return survived fraction.
/// Does not alter the authoritative world; no bullet means every move is safe.
pub fn reconstructed_dodge(game: &Game, tank: usize) -> [f32; 9] {
    use crate::sandbox::{apply_action, make_sandbox, OppModel};
    if !game.tanks[tank].alive || game.bullets.is_empty() { return [1.0; 9]; }
    let mut result = [1.0; 9];
    for (i, value) in result.iter_mut().enumerate() {
        let mut sb = make_sandbox(game, tank, OppModel::L1, 0);
        apply_action(&mut sb, crate::score::CANDIDATES[i * 2]);
        let other = &mut sb.tanks[1];
        other.forward = false; other.backup = false;
        other.turn_left = false; other.turn_right = false; other.fire = false;
        for frame in 0..58 {
            sb.step();
            if !sb.tanks[0].alive { *value = frame as f32 / 58.0; break; }
            if sb.frozen { break; }
        }
    }
    result
}

