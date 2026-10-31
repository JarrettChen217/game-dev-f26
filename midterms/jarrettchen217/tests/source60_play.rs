#![allow(dead_code)]
#[path="../tank_game/laika_60hz/training/source/play_lib.rs"] mod play;
pub use play::{constants,game,laika,maze,rng,ballistics,duel,score,sandbox,risk,hybrid_obs};

#[test]
fn watch_is_exact_retained_training_with_one_game() {
    let mut baseline=play::training::Training::new(17);
    let mut observed=play::Play::new(17,false);
    for a in [8,14,15,2,3,9,10,8,17] {
        baseline.step(a);observed.step(a,14);
        assert_eq!(observed.env.observation.values,baseline.observation.values);
        assert_eq!(observed.env.observation.bullet_mask,baseline.observation.bullet_mask);
        assert_eq!(observed.env.game.frame,baseline.game.frame);
        assert_eq!(observed.env.game.rng.seed,baseline.game.rng.seed);
        assert_eq!(observed.env.reward,baseline.reward);
    }
}
#[test]
fn human_controls_seat_one_and_actor_history_stays_seat_zero() {
    let mut p=play::Play::new(17,true);
    assert_eq!(p.env.game.ai_enabled,vec![false,false]);
    assert!(p.env.game.ais[1].is_none(),"human seat must not retain an AI object");
    // Use an explicit open arena: a seeded maze may block forward motion.
    p.env.game=game::Game::range_arena(17,12,5);
    p.env.game.ai_enabled=vec![false,false];
    let scale=p.env.game.scale;
    p.env.game.tanks[1].x=4.5*scale;p.env.game.tanks[1].y=2.5*scale;
    p.env.game.tanks[1].rotation=90.;
    let before=(p.env.game.tanks[1].x,p.env.game.tanks[1].y);
    p.step(8,14);
    assert_ne!(before,(p.env.game.tanks[1].x,p.env.game.tanks[1].y));
    assert_eq!(p.env.history.frames,1);
    assert_eq!(p.env.observation.values[1007..1010],[0.5,0.5,0.]);
    assert_eq!(p.env.game.laika_calls,0);
    let frame=p.env.game.frame;
    assert_eq!(p.step(18,8),-1);assert_eq!(p.step(8,18),-1);
    assert_eq!(p.env.game.frame,frame);
}

#[test]
fn selected_controller_is_the_only_native_ai_and_shares_initial_world() {
    let mut external=play::Play::new(1000,true);
    let mut native=play::Play::new(1000,true);
    assert!(external.set_opponent(false));
    assert!(native.set_opponent(true));
    assert_eq!(external.env.observation.values,native.env.observation.values);
    assert_eq!(external.env.game.rng.seed,native.env.game.rng.seed);
    assert_eq!(native.env.game.ai_enabled,vec![true,false]);
    assert!(native.env.game.ais[0].is_some());assert!(native.env.game.ais[1].is_none());
    for _ in 0..20 {external.step(14,8);native.step(8,8);}
    assert_eq!(external.env.game.laika_calls,0);
    assert!(native.env.game.laika_calls>0);
    assert!(!native.set_opponent(false),"do not change controller within a round");
}

#[test]
fn external_opponent_actions_are_not_replaced_by_laika() {
    let mut p=play::Play::new(17,true);
    assert!(p.set_opponent(false));
    p.env.game=game::Game::range_arena(17,12,5);
    p.env.game.ai_enabled=vec![false,false];
    let scale=p.env.game.scale;
    p.env.game.tanks[0].x=4.5*scale;p.env.game.tanks[0].y=2.5*scale;
    p.env.game.tanks[0].rotation=90.;
    let x=p.env.game.tanks[0].x;
    p.step(14,8);
    assert!(p.env.game.tanks[0].x>x);
    assert_eq!(p.env.game.laika_calls,0);
    assert!(p.env.game.tanks[0].forward);
}

#[test]
fn practice_and_lessons_step_the_same_native_game_without_ai() {
    for kind in 1..=6 {
        let mut p=play::Play::fixture(1000,kind).unwrap();
        assert_eq!(p.env.game.ai_enabled,vec![false,false]);
        assert!(p.env.game.ais.iter().all(|a|a.is_none()));
        let mut expected=p.env.game.clone();
        for _ in 0..5 {
            p.step(8,14);
            let t=&mut expected.tanks[1];t.forward=true;t.backup=false;t.turn_left=false;t.turn_right=false;t.fire=false;
            expected.step();
            assert_eq!(p.env.game.tanks[1].x,expected.tanks[1].x);
            assert_eq!(p.env.game.tanks[1].y,expected.tanks[1].y);
            assert_eq!(p.env.game.tanks[1].rotation,expected.tanks[1].rotation);
        }
    }
}
