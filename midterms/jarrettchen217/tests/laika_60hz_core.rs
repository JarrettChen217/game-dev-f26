// Compile with --cfg baseline to prove the time-conservation assertions reject
// the retained25Hz source. No test mutates the original source files.
#![allow(dead_code)]
#[cfg(baseline)] #[path="../tank_game/original_laika/source/constants.rs"] mod constants;
#[cfg(not(baseline))] #[path="../tank_game/laika_60hz/source/constants.rs"] mod constants;
#[cfg(baseline)] #[path="../tank_game/original_laika/source/game.rs"] mod game;
#[cfg(not(baseline))] #[path="../tank_game/laika_60hz/source/game.rs"] mod game;
#[cfg(baseline)] #[path="../tank_game/original_laika/source/laika.rs"] mod laika;
#[cfg(not(baseline))] #[path="../tank_game/laika_60hz/source/laika.rs"] mod laika;
#[path="../tank_game/original_laika/source/maze.rs"] mod maze;
#[path="../tank_game/original_laika/source/rng.rs"] mod rng;
#[path="../tank_game/original_laika/source/ballistics.rs"] mod ballistics;

fn arena() -> game::Game { game::Game::range_arena(1000, 12, 5) }
fn close(a:f64,b:f64) { assert!((a-b).abs()<1e-7,"actual {a}, expected {b}"); }

#[test]
fn one_second_forward_preserves_two_cells() {
    let mut g=arena(); let s=g.scale;
    g.tanks[0].x=2.5*s; g.tanks[0].y=0.5*s; g.tanks[0].rotation=90.;
    g.tanks[0].forward=true;
    for _ in 0..60 { game::tank_update(&mut g,0); }
    close(g.tanks[0].x,4.5*s);
}
#[test]
fn one_second_reverse_preserves_one_and_quarter_cells() {
    let mut g=arena(); let s=g.scale;
    g.tanks[0].x=4.5*s; g.tanks[0].y=0.5*s; g.tanks[0].rotation=90.;
    g.tanks[0].backup=true;
    for _ in 0..60 { game::tank_update(&mut g,0); }
    close(g.tanks[0].x,3.25*s);
}
#[test]
fn one_second_turn_preserves_250_degrees() {
    let mut g=arena(); g.tanks[0].rotation=0.;g.tanks[0].x=2.5*g.scale;g.tanks[0].y=0.5*g.scale;
    g.tanks[0].turn_right=true;g.tanks[0].turn_right_amount=Some(1.);
    for _ in 0..60 { game::tank_update(&mut g,0); }
    close(g.tanks[0].rotation,-110.);
}
#[test]
fn bullet_travels_two_and_quarter_cells_per_second() {
    let mut g=arena();let s=g.scale;
    for t in &mut g.tanks {t.alive=false;}
    g.inject_bullet(0,2.5*s,0.5*s,90.);
    let x=g.bullets[0].x;
    for _ in 0..60 {game::bullet_update(&mut g,0);}
    close(g.bullets[0].x-x,2.25*s);
}
#[test]
fn bullet_expires_on_the_six_hundredth_step() {
    let mut g=arena();let s=g.scale;
    for t in &mut g.tanks {t.alive=false;}
    g.inject_bullet(0,2.5*s,0.5*s,90.);
    for _ in 0..599 {game::bullet_update(&mut g,0);}
    assert!(!g.bullets[0].removed,"expired before10seconds");
    game::bullet_update(&mut g,0);assert!(g.bullets[0].removed);
}
#[test]
fn settlement_is_three_seconds_and_awards_only_when_frozen() {
    let mut g=arena();g.destroy_tank(1);
    for _ in 0..179 {g.step();}
    assert!(!g.frozen,"settlement ended before3seconds");assert_eq!(g.scores[0],0);
    g.step();assert!(g.frozen);assert_eq!(g.scores[0],1);
}

#[cfg(not(baseline))]
#[test]
fn laika_action_logic_runs_all_sixty_alive_unfrozen_steps() {
    let mut g=arena();g.weapons_disabled=vec![true,true];
    g.ais[0]=Some(laika::LaikaAI::new(g.scale,0));
    for _ in 0..60 {g.step();}
    assert_eq!(g.frame,60);assert_eq!(g.laika_calls,60);
    assert!(g.tanks[0].alive);
}

#[cfg(not(baseline))]
#[test]
fn timed_reverse_keeps_point_twelve_seconds_of_displacement() {
    let mut g=arena();let s=g.scale;g.tanks[0].x=4.5*s;g.tanks[0].y=0.5*s;g.tanks[0].rotation=90.;
    let mut ai=laika::LaikaAI::new(s,0);
    ai.my_goal.period=1e6;ai.my_goal.update_continuously=false;
    ai.my_actions=vec![laika::Action::Backup{dist:3.0}];
    for _ in 0..9 {laika::laika_step(&mut g,&mut ai);game::tank_update(&mut g,0);}
    close(g.tanks[0].x,4.5*s-0.15*s);
    assert!(ai.my_actions.is_empty());
}

#[cfg(not(baseline))]
#[test]
fn newly_revealed_timed_action_keeps_the_original_extra_interval() {
    let mut g=arena();let s=g.scale;g.tanks[0].x=4.5*s;g.tanks[0].y=0.5*s;g.tanks[0].rotation=90.;
    let mut ai=laika::LaikaAI::new(s,0);ai.my_goal.period=1e6;ai.my_goal.update_continuously=false;
    // The completed turn reveals Backup without first decrementing its count.
    // Original3+1 intervals are0.16s, hence0.2cell of reverse displacement.
    ai.my_actions=vec![laika::Action::Backup{dist:3.0},laika::Action::TurnTo{angle:90.}];
    for _ in 0..11 {laika::laika_step(&mut g,&mut ai);game::tank_update(&mut g,0);}
    close(g.tanks[0].x,4.5*s-0.2*s);
}

#[test]
fn discrete_turn_wrap_preserves_angular_velocity() {
    let mut g=arena();g.tanks[0].x=2.5*g.scale;g.tanks[0].y=0.5*g.scale;
    g.tanks[0].rotation=170.;g.tanks[0].turn_right=true;
    for _ in 0..60 {game::tank_update(&mut g,0);}
    close(g.tanks[0].rotation,60.);
}

#[test]
fn held_fire_is_one_edge_and_new_bullet_waits_for_next_step() {
    let mut g=arena();g.tanks[0].x=2.5*g.scale;g.tanks[0].y=0.5*g.scale;
    g.tanks[0].rotation=90.;g.tanks[0].fire=true;
    g.step();assert_eq!(g.bullets.len(),1);
    let x=g.bullets[0].x;let life=g.bullets[0].lifetime;
    g.step();assert!(g.bullets[0].x>x);assert_eq!(g.bullets[0].lifetime,life-1);
    for _ in 0..10 {g.step();}
    assert_eq!(g.round_shots_fired[0],1);
    g.tanks[0].fire=false;g.step();g.tanks[0].fire=true;g.step();
    assert_eq!(g.round_shots_fired[0],2);
}

#[test]
fn wall_push_never_walks_through_the_outer_ring() {
    let mut g=arena();g.tanks[0].x=10.5*g.scale;g.tanks[0].y=0.5*g.scale;
    g.tanks[0].rotation=90.;g.tanks[0].forward=true;let mut blocked=false;
    for _ in 0..360 {
        game::tank_update(&mut g,0);blocked |= g.tanks[0].hit_something;
        assert!(!game::any_side_hit(&g.wall_grid,&g.tanks[0]));
        assert!(g.tanks[0].x<12.*g.scale);
    }
    assert!(blocked);
}

#[cfg(not(baseline))]
#[test]
fn source_pursuit_gets_around_the_first_barrier() {
    let mut g=arena();let s=g.scale;
    g.tanks[0].x=2.5*s;g.tanks[0].y=2.5*s;g.tanks[0].rotation=90.;
    g.tanks[1].x=10.5*s;g.tanks[1].y=2.5*s;
    g.ais[0]=Some(laika::LaikaAI::new(s,0));
    let mut crossed=false;let mut blocked=0;
    for _ in 0..1200 {
        g.step();if g.tanks[0].x>4.5*s {crossed=true;break;}
        if g.tanks[0].hit_something {blocked+=1;}
        assert!(g.tanks[0].alive);
    }
    assert!(crossed,"source pursuit failed to get around barrier; blocked {blocked}");
}

#[cfg(not(baseline))]
#[test]
fn incoming_line_is_detected_and_dodged_by_real_source_logic() {
    let mut g=arena();let s=g.scale;
    g.tanks[0].x=2.5*s;g.tanks[0].y=2.5*s;g.tanks[0].rotation=90.;
    g.tanks[1].x=10.5*s;g.tanks[1].y=4.5*s;
    g.tank_fields[0]=(2,2);g.tank_fields[1]=(10,4);
    g.inject_bullet(1,2.68*s,1.*s,180.);
    assert!(laika::detects_enemy_bullet_danger(&g,0));
    let mut ai=laika::LaikaAI::new(s,0);ai.my_goal.period=0.;g.ais[0]=Some(ai);
    let mut dodged=false;
    for _ in 0..180 {
        g.step();
        if let Some(ai)=&g.ais[0] {dodged |= matches!(ai.my_goal.kind,laika::GoalKind::DodgeBullet{..});}
        assert!(g.tanks[0].alive,"dodge failed at{}",g.frame);
    }
    assert!(dodged);
    assert!((g.tanks[0].x-2.5*s).abs()>0.01 || (g.tanks[0].rotation-90.).abs()>0.01);
}

#[test]
fn ricochet_reverses_velocity_without_changing_speed() {
    let mut g=arena();let s=g.scale;for t in &mut g.tanks {t.alive=false;}
    g.inject_bullet(0,3.*s,0.5*s,90.);let speed=g.bullets[0].x_speed;
    for _ in 0..250 {
        game::bullet_update(&mut g,0);
        if g.bullets[0].has_bounced {break;}
    }
    assert!(g.bullets[0].has_bounced);close(g.bullets[0].x_speed,-speed);
}

#[cfg(not(baseline))]
#[test]
fn second_death_resets_source_settlement_and_finishes_as_draw() {
    let mut g=arena();g.destroy_tank(1);for _ in 0..90 {g.step();}
    g.destroy_tank(0);
    for _ in 0..179 {g.step();assert!(!g.frozen);}
    g.step();assert!(g.frozen);assert_eq!(g.alive_count,0);assert_eq!(g.scores,vec![0,0]);
}

#[cfg(not(baseline))]
#[test]
fn recurring_goal_deadlines_do_not_accumulate_rounding_drift() {
    let mut g=arena();let mut ai=laika::LaikaAI::new(g.scale,0);
    // A high-priority incumbent cannot be displaced in this bounded sample.
    //16 source intervals are0.64s. Subsequent unselected checks are40ms apart.
    ai.my_goal.priority=1e9;let mut events=Vec::new();
    for tick in 1..=240 {
        let priority=ai.my_goal.priority;
        laika::make_decisions_and_update_goal(&mut g,&mut ai);
        if ai.my_goal.priority<priority {events.push(tick as f64/60.);}
    }
    for (index,time) in events.iter().enumerate() {
        let expected=0.64+index as f64*0.04;
        assert!(*time>=expected-1e-9 && *time-expected<=1./60.+1e-9,
                "goal{index}: actual{time} expected{expected}");
    }
    assert_eq!(events.len(),85);
}

#[cfg(not(baseline))]
#[test]
fn legacy_forward_turn_retains_source_double_decrement_duration() {
    let mut g=arena();let s=g.scale;g.tanks[0].x=2.5*s;g.tanks[0].y=0.5*s;g.tanks[0].rotation=90.;
    let mut ai=laika::LaikaAI::new(s,0);ai.my_goal.period=1e6;ai.my_goal.update_continuously=false;
    ai.my_actions=vec![laika::Action::ForwardAndTurn{dist:5 as _,dir:laika::Dir::Right}];
    for _ in 0..20 {
        laika::laika_step(&mut g,&mut ai);game::tank_update(&mut g,0);
        if ai.my_actions.is_empty() {break;}
    }
    //5 source counter units double-decrement to3 intervals,0.12s ->30deg.
    close(g.tanks[0].rotation,120.);
}
