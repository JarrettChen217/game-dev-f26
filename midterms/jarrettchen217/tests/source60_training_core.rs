#![allow(dead_code)]
#[path="../tank_game/laika_60hz/training/source/lib.rs"] mod training;
pub use training::{constants,game,laika,maze,rng,ballistics,duel,score,sandbox,risk,hybrid_obs};

#[test]
fn reference_velocity_units_and_mask_are_real() {
    let mut e=training::Training::new(1000);
    e.game=game::Game::range_arena(1000,12,5);
    let half=e.game.wall_half_t;
    e.boxes=e.game.walls.iter().map(|&[x1,y1,x2,y2]|[x1.min(x2)-half,y1.min(y2)-half,x1.max(x2)+half,y1.max(y2)+half]).collect();
    let s=e.game.scale;
    e.game.tanks[0].x=2.5*s;e.game.tanks[0].y=0.5*s;e.game.tanks[0].rotation=90.;
    e.step(14);
    assert!((e.observation.values[860]-0.16).abs()<1e-6);
    e.game.inject_bullet(0,5.*s,0.5*s,90.);
    e.encode();
    assert!(e.observation.bullet_mask[0]);
    assert!((e.observation.values[902]-0.025714286).abs()<1e-6);
}
#[test]
fn time_normalized_terminal_rewards_match_reference_seconds() {
    assert_eq!(duel::win_reward(600),1.);
    assert!((duel::win_reward(1200)-0.6845351232142713).abs()<1e-12);
    assert_eq!(duel::win_reward(1800),0.5);
    assert_eq!(duel::style_bonus(13,241),0.25);
    assert_eq!(duel::terminal_reward(0,100,0),0.);
    assert_eq!(duel::terminal_reward(2,100,0),-0.75);
}
#[test]
fn observation_does_not_read_hidden_ai_goals_or_mutate_authority() {
    let mut e=training::Training::new(17);let before=e.observation.values;
    let frame=e.game.frame;let rng=e.game.rng.seed;
    e.game.ais[1].as_mut().unwrap().my_goal.priority=12345.;
    e.encode();assert_eq!(before,e.observation.values);
    assert_eq!(e.game.frame,frame);assert_eq!(e.game.rng.seed,rng);
}
#[test]
fn task_clock_draw_is_terminal_and_not_an_external_cutoff() {
    let mut e=training::Training::new(1000);
    e.game=game::Game::range_arena(1000,12,5);
    e.game.frame=1799;e.history.frames=1799;
    e.step(8);assert_eq!(e.outcome,4);assert_eq!(e.reward,-0.75);
    let frame=e.game.frame;assert_eq!(e.step(8),0);assert_eq!(e.game.frame,frame);
    assert_eq!(e.step(18),-1);
}
