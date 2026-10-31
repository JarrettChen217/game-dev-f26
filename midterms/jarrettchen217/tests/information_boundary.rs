// Information boundary for the u19588 player: its schema24 observation is a
// function of what is on screen plus its own past actions, never hidden state.
// Each hidden field is perturbed on a copy of a live round and the 1028 features
// and 10-slot bullet mask must be bit-identical; a visible change must move them.
#![allow(dead_code)]
#[path="../tank_game/laika_60hz/training/source/play_lib.rs"] mod play;
pub use play::{constants,game,laika,maze,rng,ballistics,duel,score,sandbox,risk,hybrid_obs};

fn live_round() -> play::training::Training {
    let mut env = play::training::Training::new(17);
    // A short real opening (drive, turn, fire) so bullets and history exist.
    for a in [8, 14, 15, 2, 3, 9, 10, 8, 17, 8, 8, 2] { env.step(a); }
    env
}

fn observe(env: &mut play::training::Training) -> (Vec<f32>, Vec<bool>) {
    env.encode();
    (env.observation.values.to_vec(), env.observation.bullet_mask.to_vec())
}

fn assert_hidden(name: &str, change: impl Fn(&mut play::training::Training)) {
    let mut base = live_round();
    let expected = observe(&mut base);
    let mut env = live_round();
    change(&mut env);
    assert_eq!(observe(&mut env), expected, "hidden field leaked into the observation: {name}");
}

#[test]
fn seed_and_rng_state_are_not_observed() {
    assert_hidden("rng state", |e| e.game.rng.state ^= 0x5eed_1234);
    assert_hidden("rng seed", |e| e.game.rng.seed = e.game.rng.seed.wrapping_add(99));
    assert_hidden("round seed", |e| e.game.seed = e.game.seed.wrapping_add(99));
}

#[test]
fn opponent_buttons_this_frame_are_not_observed() {
    assert_hidden("opponent buttons", |e| {
        let t = &mut e.game.tanks[1];
        t.forward = !t.forward; t.backup = !t.backup;
        t.turn_left = !t.turn_left; t.turn_right = !t.turn_right; t.fire = !t.fire;
    });
}

#[test]
fn opponent_planner_state_is_not_observed() {
    assert_hidden("Laika planner", |e| {
        let ai = e.game.ais[1].as_mut().expect("seat 1 is the native Laika opponent");
        ai.aggresiveness += 3.0; ai.cowardness += 3.0; ai.longest_path_to_shoot *= 2.0;
        ai.max_time_to_dodge_bullet *= 2.0;
    });
    assert_hidden("planner bookkeeping", |e| { e.game.laika_calls += 1000; e.game.laika_nanos += 1; });
}

#[test]
fn visible_change_is_observed() {
    // Control: the test would be vacuous if the encoder ignored the opponent entirely.
    let mut base = live_round();
    let before = observe(&mut base);
    let mut moved = live_round();
    moved.game.tanks[1].x += 0.5 * moved.game.scale;
    assert_ne!(observe(&mut moved).0, before.0);
}
