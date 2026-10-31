// The player's five operations on the native60Hz duel, as the model sees them:
// reset = Training::new(seed), observe = .observation, legal_actions = 0..18,
// step(action) -> 1 accepted / -1 illegal / 0 already over, outcome = .outcome
// (0 running, 1 win, 2 loss, 3 both destroyed, 4 draw by time).
#![allow(dead_code)]
#[path="../tank_game/laika_60hz/training/source/play_lib.rs"] mod play;
pub use play::{constants,game,laika,maze,rng,ballistics,duel,score,sandbox,risk,hybrid_obs};
use play::training::Training;

const LIMIT: u32 = duel::DUEL_FRAMES + duel::DUEL_GRACE_FRAMES;

fn digest(values: &[f32]) -> u64 {
    // FNV-1a over the exact bits, so any change to the observation is visible.
    values.iter().flat_map(|v| v.to_bits().to_le_bytes()).fold(0xcbf29ce484222325u64,
        |h, b| (h ^ b as u64).wrapping_mul(0x100000001b3))
}

#[test]
fn every_action_in_the_declared_range_is_legal_and_others_are_rejected() {
    assert_eq!(duel::DUEL_ACTIONS, 18);
    for action in 0..18u16 {
        let mut env = Training::new(5);
        assert_eq!(env.step(action), 1, "legal action {action} was refused");
        assert_eq!(env.game.frame, 1);
    }
    let mut env = Training::new(5);
    let before = (env.game.frame, env.observation.values.to_vec(), env.history.frames);
    for illegal in [18u16, 19, 255, u16::MAX] {
        assert_eq!(env.step(illegal), -1, "illegal action {illegal} was accepted");
    }
    // A rejected action changes nothing: no tick, no history, same observation.
    assert_eq!((env.game.frame, env.observation.values.to_vec(), env.history.frames), before);
}

#[test]
fn a_finished_round_is_terminal_and_later_steps_change_nothing() {
    let mut env = Training::new(11);
    let mut frames = 0;
    while env.outcome == 0 { env.step(8); frames += 1; assert!(frames <= LIMIT, "round never ended"); }
    assert!((1..=4).contains(&env.outcome));
    let (outcome, frame) = (env.outcome, env.game.frame);
    assert_eq!(env.step(8), 0);
    assert_eq!((env.outcome, env.game.frame), (outcome, frame));
}

#[test]
fn a_round_with_nobody_fighting_ends_as_a_draw_within_the_episode_limit() {
    let mut env = Training::new(3);
    env.game.ai_enabled = vec![false, false];
    env.game.ais[1] = None;
    let mut steps = 0;
    while env.outcome == 0 { assert_eq!(env.step(4), 1); steps += 1; assert!(steps <= LIMIT); }
    assert_eq!(env.outcome, 4, "a passive round must end as a time draw");
    assert!(steps >= duel::DUEL_FRAMES && steps <= LIMIT, "ended at {steps}");
}

#[test]
fn same_seed_and_actions_reproduce_the_round_exactly() {
    let tape: Vec<u16> = (0..600u32).map(|i| ((i * 7 + i / 13) % 18) as u16).collect();
    let run = || {
        let mut env = Training::new(1000);
        let mut trace = Vec::new();
        for &a in &tape { if env.step(a) != 1 { break; } trace.push(digest(&env.observation.values)); }
        (trace, env.outcome, env.game.frame)
    };
    assert_eq!(run(), run());
}

#[test]
fn pinned_regression_of_a_fixed_opening() {
    // Recorded from this submission's engine; a rule or observation change moves it.
    let mut env = Training::new(1000);
    for i in 0..240u32 { env.step(((i * 5) % 18) as u16); }
    let found = (env.game.frame, env.outcome, digest(&env.observation.values));
    let expected: (i64, u8, u64) = (PINNED_FRAME, PINNED_OUTCOME, PINNED_DIGEST);
    assert_eq!(found, expected);
}

const PINNED_FRAME: i64 = 240;
const PINNED_OUTCOME: u8 = 0;
const PINNED_DIGEST: u64 = 1918593998315174968;
