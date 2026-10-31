//!Retained source sandbox subset, adapted for60Hz diagnostic fields only.
use crate::game::{Bullet, Game, Tank};
use crate::laika::LaikaAI;
use crate::rng::Rng;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum OppModel {
    /// Run the scripted AI's algorithm with fresh internal state.
    L2,
    /// Freeze whatever buttons the opponent is currently holding.
    L1,
}

/// A stepping-compatible clone whose `tanks[0]` is `me`.
pub fn make_sandbox(g: &Game, me: usize, opp_model: OppModel, rng_seed: u32) -> Game {
    let other = 1 - me;
    let order = [me, other];

    let tanks: Vec<Tank> = order.iter().map(|&i| g.tanks[i]).collect();
    let bullets: Vec<Bullet> = g
        .bullets
        .iter()
        .map(|b| {
            let mut c = *b;
            // Owner is an index into the reordered tank list.
            c.owner = if b.owner == me { 0 } else { 1 };
            c
        })
        .collect();
    let tank_fields: Vec<(i64, i64)> = order.iter().map(|&i| g.tank_fields[i]).collect();
    let scores: Vec<i32> = order.iter().map(|&i| g.scores[i]).collect();

    let mut sb = Game {
        // Hidden information scrubbed.
        rng: Rng::new(rng_seed),
        seed: g.seed,
        tanks_count: g.tanks_count,
        settings_max_bullets: g.settings_max_bullets,
        weapons_disabled: g.weapons_disabled.clone(),

        // Mutable state copied.
        alive_count: g.alive_count,
        end_count: g.end_count,
        reset_count: g.reset_count,
        frozen: g.frozen,
        shake: g.shake,
        crate_timer: g.crate_timer,
        scores,
        round_number: g.round_number,
        frame: g.frame,
        laika_calls:0,
        laika_nanos:0,
        round_start_frame: g.round_start_frame,
        events: Vec::new(),
        hit_records: Vec::new(),
        tank_fields,
        tanks,
        bullets,
        bullet_depth: g.bullet_depth,
        round_shots_fired: order.iter().map(|&i| g.round_shots_fired[i]).collect(),

        // Shared, read-only for the duration of a round.
        maze: g.maze.clone(),
        scale: g.scale,
        walls: g.walls.clone(),
        wall_half_t: g.wall_half_t,
        wall_grid: g.wall_grid.clone(),
        reachable: g.reachable.clone(),
        reachable_index: g.reachable_index.clone(),
        distances_for_maze: g.distances_for_maze.clone(),
        dead_ends: g.dead_ends.clone(),

        ais: vec![None, None],
        ai_enabled: vec![false, false],
    };

    if opp_model == OppModel::L2 {
        sb.ais[1] = Some(LaikaAI::new(sb.scale, 1));
    }
    sb
}

/// Write a (throttle, turn, fire) triple onto the sandbox's own tank.
pub fn apply_action(sb: &mut Game, action: [u8; 3]) {
    let me = &mut sb.tanks[0];
    me.forward = action[0] == 2;
    me.backup = action[0] == 0;
    me.turn_left = action[1] == 0;
    me.turn_right = action[1] == 2;
    me.fire = action[2] == 1;
    me.forward_amount = None;
    me.backup_amount = None;
    me.turn_left_amount = None;
    me.turn_right_amount = None;
}

