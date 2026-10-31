//!60Hz adaptation; original source retained separately and attributed in LICENSE.
//! Port of `killfield/src/laika.js` — the scripted AI opponent.
//!
//! Three phases run every frame, in this order:
//!   1. `make_decisions_and_update_goal` — score every candidate goal, keep the best
//!   2. `decide_actions_to_achieve_goal` — compile the goal into an action stack
//!   3. `set_input_to_do_actions`        — pop the stack and write the tank's inputs
//!
//! The action stack is LIFO: an action is popped, re-pushed if unfinished, and
//! then the new top of stack decides this frame's input.
//!
//! A fresh instance is built every round, because a dozen of its tuning
//! constants are derived from that round's cell size. Nothing carries over.
//!
//! Several original quirks are reproduced deliberately and must not be
//! "corrected" — they are why the opponent feels the way it does:
//!   - `run_away`'s summed distance field is (W-1)x(H-1), leaving the last row
//!     and column permanently NaN.
//!   - Ballistics are simulated one substep per frame, three times coarser than
//!     the real bullet, so its aim is approximate by construction.
//!   - Closest-approach uses Manhattan distance, gated by cell distance.
//!   - It dodges its own bullets, because trajectory scanning ignores ownership.
//!   - `ForwardAndTurn` falls through into the backup case, decrementing its
//!     distance counter twice.
//!   - `TurnTo`'s completion test compares raw (unnormalised) angles.
//!
//! Porting hazard, handled: JS `Math.round` rounds halves toward +Infinity
//! (`Math.round(-2.5) === -2`), while Rust's `f64::round` rounds halves away
//! from zero (`-3`). Both places that snap an angle to the turn lattice use
//! `js_round` below, not `f64::round`.

use crate::ballistics::{cell_dist, check_bullet_path, check_path_for_collision, ShotOutcome};
use crate::constants as C;
use crate::game::{expanded_hit_check, Game, HIT_POINTS_FRONT, HIT_POINTS_LEFT, HIT_POINTS_REAR};
use crate::maze::{follow_gradient_with_distances_and_dead_ends, shortest_path_with_distances};

const PI: f64 = std::f64::consts::PI;

/// JS `Math.round`: halves go toward +Infinity, not away from zero.
#[inline]
fn js_round(x: f64) -> f64 {
    (x + 0.5).floor()
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Dir {
    Left,
    Right,
}

#[derive(Clone, Debug)]
pub enum GoalKind {
    Idle,
    ShootAfter {
        target: usize,
    },
    DodgeBullet {
        x: f64,
        y: f64,
        closest: (f64, f64),
        dist: f64,
        t: f64,
        dir: (f64, f64),
        max_time: f64,
        max_dist: f64,
    },
    /// `summed` is the deliberately undersized (w-1) x (h-1) field.
    RunAway {
        summed: Vec<f64>,
        sw: usize,
        sh: usize,
    },
    BackAway,
    DriveTo {
        x: usize,
        y: usize,
    },
}

#[derive(Clone, Debug)]
pub struct Goal {
    pub kind: GoalKind,
    pub priority: f64,
    pub period: f64,
    pub id: u64,
    pub update_continuously: bool,
}

#[derive(Clone, Copy, Debug)]
pub enum Action {
    DriveToField { x: usize, y: usize },
    DriveToPos { x: f64, y: f64, can_reverse: bool },
    TurnTo { angle: f64 },
    FireWeapon { delay: f64 },
    Forward { dist: f64 },
    Backup { dist: f64 },
    ForwardAndTurn { dist: i32, dir: Dir },
    /// Internal remaining duration after converting the source double decrement.
    ForwardAndTurnTime { left: f64, dir: Dir },
    BackupAndTurn { dist: f64, dir: Dir },
    Idle,
}

#[derive(Clone, Debug)]
pub struct LaikaAI {
    pub my_tank: usize,

    pub aggresiveness: f64,
    pub cowardness: f64,
    pub longest_path_to_shoot: f64,
    pub longest_path_to_not_hesitate_to_shoot: f64,
    pub longest_path_to_run: f64,
    pub max_stuck_time: f64,
    pub idle_drive_toward_enemy_priority: f64,
    pub max_closest_cell_distance: f64,
    pub max_closest_distance: f64,
    pub max_time_to_dodge_bullet: f64,
    pub max_dist_to_dodge_bullet: f64,
    pub max_cell_dist_to_dodge_bullet: f64,

    pub stuck_time: f64,
    pub current_aggresiveness: f64,
    pub goal_id: u64,
    pub my_goal: Goal,
    pub my_actions: Vec<Action>,
}

impl LaikaAI {
    pub fn new(scale: f64, my_tank: usize) -> Self {
        let max_closest_cell_distance = 2.0;
        let max_time_to_dodge_bullet = 75.0 / C::STEP_25;
        LaikaAI {
            my_tank,
            aggresiveness: 0.5,
            cowardness: 0.7000000000000001,
            longest_path_to_shoot: 7.0,
            longest_path_to_not_hesitate_to_shoot: 2.0,
            longest_path_to_run: 10.0,
            max_stuck_time: 1.0,
            idle_drive_toward_enemy_priority: 0.1,
            max_closest_cell_distance,
            max_closest_distance: scale * max_closest_cell_distance,
            max_time_to_dodge_bullet,
            max_dist_to_dodge_bullet: 4.0 * scale,
            max_cell_dist_to_dodge_bullet: (max_time_to_dodge_bullet * C::BULLETSPEED) / 50.0,
            stuck_time: 0.0,
            current_aggresiveness: 0.5,
            goal_id: 1,
            my_goal: Goal {
                kind: GoalKind::Idle,
                priority: 0.0,
                period: 16.0,
                id: 0,
                update_continuously: true,
            },
            my_actions: Vec::new(),
        }
    }

    fn update_goal(&mut self, temp: Goal) {
        if self.my_goal.priority < temp.priority {
            self.my_goal = temp;
        }
    }

    fn next_id(&mut self) -> u64 {
        let id = self.goal_id;
        self.goal_id += 1;
        id
    }

    fn shot(&self, g: &Game, angle: f64) -> crate::ballistics::ShotResult {
        check_bullet_path(
            g,
            self.my_tank,
            angle,
            self.max_closest_distance,
            self.max_closest_cell_distance,
        )
    }

    /// Turn the short way round, with no dead zone.
    fn turn_toward(&self, g: &mut Game, target: f64, cur: f64) {
        let my = self.my_tank;
        if target > cur {
            let long = (target - cur).abs() > 180.0;
            g.tanks[my].turn_left = long;
            g.tanks[my].turn_right = !long;
        } else if target < cur {
            let long = (target - cur).abs() > 180.0;
            g.tanks[my].turn_left = !long;
            g.tanks[my].turn_right = long;
        } else {
            g.tanks[my].turn_left = false;
            g.tanks[my].turn_right = false;
        }
    }
}

// ------------------------------------------------------- threat assessment

/// For each bullet, find its closest approach to me and raise a dodge goal if
/// that approach is both near and unobstructed. Ownership is not checked, so
/// Laika will dodge its own shots.
fn dodge_trajectories(
    g: &Game,
    ai: &mut LaikaAI,
    fieldx: i64,
    fieldy: i64,
    max_time_to_dodge: f64,
    max_dist_to_dodge: f64,
    max_cell_dist_to_dodge: f64,
    hit_check_interval: i32,
    check_bounce: bool,
    enemy_only: bool,
) -> Option<Goal> {
    let scale = g.scale;
    let my = g.tanks[ai.my_tank];
    let mut best_dist = max_dist_to_dodge;
    let mut result: Option<Goal> = None;
    let hci = hit_check_interval as f64;

    for bi in 0..g.bullets.len() {
        let b = g.bullets[bi];
        if enemy_only && b.owner == ai.my_tank {
            continue;
        }
        let bx = b.x;
        let by = b.y;
        let cell_x = (bx / scale).floor() as i64;
        let cell_y = (by / scale).floor() as i64;
        if !(cell_dist(g, fieldx, fieldy, cell_x, cell_y) <= max_cell_dist_to_dodge) {
            continue;
        }

        let mut x2 = b.x + b.x_speed * hci;
        let mut y2 = b.y + b.y_speed * hci;
        let tx = my.x;
        let ty = my.y;
        let mut seg_sq = (x2 - bx) * (x2 - bx) + (y2 - by) * (y2 - by);
        let mut t = if seg_sq != 0.0 {
            ((tx - bx) * (x2 - bx) + (ty - by) * (y2 - by)) / seg_sq
        } else {
            0.0
        };

        if t > -1.0 / C::STEP_25 && t < max_time_to_dodge {
            let cx = bx + t * (x2 - bx);
            let cy = by + t * (y2 - by);
            let dx = tx - cx;
            let dy = ty - cy;
            let dist = (dx * dx + dy * dy).sqrt();
            let mut col = if dist > 0.0 {
                check_path_for_collision(
                    g,
                    cx,
                    cy,
                    dx / dist,
                    dy / dist,
                    1,
                    dist.ceil(),
                    dist.ceil(),
                )
            } else {
                None
            };
            if col.is_none() && dist < best_dist {
                let dx2 = x2 - cx;
                let dy2 = y2 - cy;
                let d2 = (dx2 * dx2 + dy2 * dy2).sqrt();
                col = if d2 > 0.0 {
                    check_path_for_collision(g, cx, cy, dx2 / d2, dy2 / d2, 1, d2.ceil(), d2.ceil())
                } else {
                    None
                };
                if col.is_none() {
                    best_dist = f64::min(best_dist, dist);
                    let id = ai.next_id();
                    result = Some(Goal {
                        kind: GoalKind::DodgeBullet {
                            x: b.x,
                            y: b.y,
                            closest: (cx, cy),
                            dist,
                            t,
                            dir: (x2 - bx, y2 - by),
                            max_time: max_time_to_dodge,
                            max_dist: max_dist_to_dodge,
                        },
                        period: 11.0,
                        priority: 1.0,
                        update_continuously: false,
                        id,
                    });
                }
            }
        }

        // Look one ricochet ahead, but only while nothing closer is already a
        // bigger worry.
        if best_dist > scale / 4.0 && check_bounce {
            let col5 = check_path_for_collision(
                g,
                bx,
                by,
                b.x_speed,
                b.y_speed,
                hit_check_interval,
                12.0 / C::STEP_25,
                b.lifetime as f64,
            );
            if let Some(c5) = col5 {
                let bx2 = c5.x;
                let by2 = c5.y;
                x2 = c5.x + c5.x_speed * hci;
                y2 = c5.y + c5.y_speed * hci;
                seg_sq = (x2 - bx2) * (x2 - bx2) + (y2 - by2) * (y2 - by2);
                t = if seg_sq != 0.0 {
                    ((tx - bx2) * (x2 - bx2) + (ty - by2) * (y2 - by2)) / seg_sq
                } else {
                    0.0
                };
                if t > 0.0 && t < max_time_to_dodge - c5.t {
                    let cx = bx2 + t * (x2 - bx2);
                    let cy = by2 + t * (y2 - by2);
                    let dx = tx - cx;
                    let dy = ty - cy;
                    let dist = (dx * dx + dy * dy).sqrt();
                    let mut col = if dist > 0.0 {
                        check_path_for_collision(
                            g,
                            cx,
                            cy,
                            dx / dist,
                            dy / dist,
                            1,
                            dist.ceil(),
                            dist.ceil(),
                        )
                    } else {
                        None
                    };
                    if col.is_none() && dist < best_dist {
                        let dx2 = cx - bx2;
                        let dy2 = cy - by2;
                        let d2 = (dx2 * dx2 + dy2 * dy2).sqrt();
                        col = if d2 > 0.0 {
                            check_path_for_collision(
                                g,
                                bx2,
                                by2,
                                dx2 / d2,
                                dy2 / d2,
                                1,
                                d2.ceil(),
                                d2.ceil(),
                            )
                        } else {
                            None
                        };
                        if col.is_none() {
                            best_dist = f64::min(best_dist, dist);
                            let id = ai.next_id();
                            result = Some(Goal {
                                kind: GoalKind::DodgeBullet {
                                    x: b.x,
                                    y: b.y,
                                    closest: (cx, cy),
                                    dist,
                                    t: t + c5.t,
                                    dir: (x2 - bx2, y2 - by2),
                                    max_time: max_time_to_dodge,
                                    max_dist: max_dist_to_dodge,
                                },
                                period: 11.0,
                                priority: 1.0,
                                update_continuously: false,
                                id,
                            });
                        }
                    }
                }
            }
        }
    }
    result
}

/// Whether Laika's own dodge detector considers an enemy projectile dangerous
/// from this exact state. Used by the reward counterfactual; normal Laika keeps
/// its original quirk of also dodging its own bullets.
pub fn detects_enemy_bullet_danger(g: &Game, tank: usize) -> bool {
    if !g.tanks.get(tank).map(|t| t.alive).unwrap_or(false) {
        return false;
    }
    let mut ai = LaikaAI::new(g.scale, tank);
    let fx = (g.tanks[tank].x / g.scale).floor() as i64;
    let fy = (g.tanks[tank].y / g.scale).floor() as i64;
    let max_time = ai.max_time_to_dodge_bullet;
    let max_dist = ai.max_dist_to_dodge_bullet;
    let max_cell_dist = ai.max_cell_dist_to_dodge_bullet;
    dodge_trajectories(
        g,
        &mut ai,
        fx,
        fy,
        max_time,
        max_dist,
        max_cell_dist,
        C::BULLETHITCHECKINTERVALS,
        true,
        true,
    )
    .is_some()
}

/// Take a free shot while dodging, if the current heading happens to line up.
fn try_to_retaliate(g: &Game, ai: &mut LaikaAI) {
    let my = ai.my_tank;
    if ai.current_aggresiveness < ai.aggresiveness / 2.0 {
        return;
    }
    if g.tanks[my].bullets_fired >= g.settings_max_bullets {
        return;
    }

    let mut found = false;
    let mut closest = C::MOVIEWIDTH + C::MOVIEHEIGHT;
    let res = ai.shot(g, g.tanks[my].rotation);
    if res.outcome == ShotOutcome::Hit {
        found = true;
    } else if res.outcome == ShotOutcome::Nothing && res.closest < closest {
        closest = res.closest;
    }

    if found || closest < ai.max_closest_distance / 2.0 {
        ai.my_actions.push(Action::FireWeapon { delay: 1.0 });
        ai.current_aggresiveness = f64::max(0.0, ai.current_aggresiveness - 0.2);
    }
}

/// Turn a cell path into stack entries. Pushed far-end first so the nearest
/// step ends up on top and executes first.
fn push_actions_to_follow_path(ai: &mut LaikaAI, scale: f64, path: &[(usize, usize)]) {
    for i in (1..path.len()).rev() {
        ai.my_actions.push(Action::DriveToField {
            x: path[i].0,
            y: path[i].1,
        });
    }
    if let Some(&(px, py)) = path.first() {
        ai.my_actions.push(Action::DriveToPos {
            x: (px as f64 + 0.5) * scale,
            y: (py as f64 + 0.5) * scale,
            can_reverse: path.len() <= 2,
        });
    }
}

// -------------------------------------------------- phase 1: choose a goal

/// Returns true when the action stack needs rebuilding.
pub fn make_decisions_and_update_goal(g: &mut Game, ai: &mut LaikaAI) -> bool {
    let scale = g.scale;
    let my = ai.my_tank;

    ai.my_goal.period -= C::STEP_25;
    if ai.my_goal.period > 1e-9 {
        return ai.my_goal.update_continuously;
    }

    let overshoot = ai.my_goal.period.max(-C::STEP_25);
    // The incumbent goal decays, so a rival only has to outlast it.
    ai.my_goal.priority *= 0.9000000000000002;
    let old_goal_id = ai.my_goal.id;
    let fx = (g.tanks[my].x / scale).floor() as i64;
    let fy = (g.tanks[my].y / scale).floor() as i64;

    // --- dodge incoming fire ---
    let dodge = dodge_trajectories(
        g,
        ai,
        fx,
        fy,
        ai.max_time_to_dodge_bullet,
        ai.max_dist_to_dodge_bullet,
        ai.max_cell_dist_to_dodge_bullet,
        C::BULLETHITCHECKINTERVALS,
        true,
        false,
    );
    if let Some(d) = dodge {
        ai.update_goal(d);
    }

    // --- hunt: worth engaging only when the enemy is a short path away ---
    if g.tanks[my].bullets_fired < g.settings_max_bullets {
        for i in 0..g.tanks_count {
            if !g.tanks[i].alive || i == my {
                continue;
            }
            let dm = match g.dist_map(fx, fy) {
                None => continue,
                Some(dm) => dm.clone(),
            };
            let (tfx, tfy) = g.tank_fields[i];
            let path = shortest_path_with_distances(
                &g.maze,
                &dm,
                fx as usize,
                fy as usize,
                tfx as usize,
                tfy as usize,
            );
            let plen = path.len() as f64;
            if plen < ai.longest_path_to_shoot {
                let pr = if plen <= ai.longest_path_to_not_hesitate_to_shoot {
                    1.0
                } else {
                    ((ai.longest_path_to_shoot - plen) / ai.longest_path_to_shoot)
                        * ai.current_aggresiveness
                };
                let id = ai.next_id();
                ai.update_goal(Goal {
                    kind: GoalKind::ShootAfter { target: i },
                    period: 11.0,
                    priority: pr,
                    update_continuously: false,
                    id,
                });
            }
        }
    }

    // --- flee when out of ammo ---
    if g.alive_count > 1 && g.tanks[my].bullets_fired == g.settings_max_bullets {
        let (w, h) = (g.maze.w, g.maze.h);
        // Original off-by-one: the field is one row and column short, so the
        // far edge of the maze is permanently NaN and never looks safe.
        let (sw, sh) = (w.saturating_sub(1), h.saturating_sub(1));
        let mut summed = vec![0.0f64; sw * sh];
        for i in 0..g.tanks_count {
            if !g.tanks[i].alive || i == my {
                continue;
            }
            if g.tanks[i].bullets_fired == g.settings_max_bullets {
                continue;
            }
            let (tfx, tfy) = g.tank_fields[i];
            let dm = g.dist_map(tfx, tfy);
            for xx in 0..sw {
                for yy in 0..sh {
                    match dm {
                        // JS filled distance grids with NaN, never null, so the
                        // null branch only ever fired for a missing whole map.
                        None => summed[xx * sh + yy] = f64::NAN,
                        Some(d) => summed[xx * sh + yy] += d[xx * h + yy],
                    }
                }
            }
        }
        let here = if (fx as usize) < sw && (fy as usize) < sh {
            summed[fx as usize * sh + fy as usize]
        } else {
            f64::NAN
        };
        if here < ai.longest_path_to_run {
            let id = ai.next_id();
            let priority = ((ai.longest_path_to_run - here) / ai.longest_path_to_run)
                * ai.cowardness
                * (g.tanks[my].bullets_fired as f64 / g.settings_max_bullets as f64);
            ai.update_goal(Goal {
                kind: GoalKind::RunAway { summed, sw, sh },
                period: 11.0,
                priority,
                update_continuously: false,
                id,
            });
        }
    }

    // --- unwedge after scraping a wall ---
    if g.tanks[my].hit_something {
        ai.stuck_time = f64::min(ai.stuck_time + 1.0, ai.max_stuck_time);
    } else {
        ai.stuck_time = 0.0;
    }
    let id = ai.next_id();
    ai.update_goal(Goal {
        kind: GoalKind::BackAway,
        period: 6.0,
        priority: ai.stuck_time / (ai.max_stuck_time - 0.1),
        update_continuously: false,
        id,
    });

    // --- otherwise drift toward someone ---
    if g.alive_count > 1 {
        let mut k = (g.rng.random() * g.tanks_count as f64).floor() as usize;
        let mut guard = 0;
        while (k == my || !g.tanks[k].alive) && guard < 1000 {
            k = (g.rng.random() * g.tanks_count as f64).floor() as usize;
            guard += 1;
        }
        if k != my {
            let (tfx, tfy) = g.tank_fields[k];
            let id = ai.next_id();
            ai.update_goal(Goal {
                kind: GoalKind::DriveTo {
                    x: tfx as usize,
                    y: tfy as usize,
                },
                period: 11.0,
                priority: ai.idle_drive_toward_enemy_priority,
                update_continuously: false,
                id,
            });
        }
    }

    if old_goal_id != ai.my_goal.id {
        ai.my_goal.period += overshoot;
        // Committing to a shot spends aggression; it regenerates while idle.
        if matches!(ai.my_goal.kind, GoalKind::ShootAfter { .. }) {
            ai.current_aggresiveness = f64::max(0.0, ai.current_aggresiveness - 0.2);
        }
        return true;
    }
    ai.my_goal.period = 1.0 + overshoot;
    ai.current_aggresiveness = f64::min(
        ai.aggresiveness,
        ai.current_aggresiveness + ai.aggresiveness / 50.0,
    );
    ai.my_goal.update_continuously
}

// ------------------------------------------------- phase 2: build the stack

pub fn decide_actions_to_achieve_goal(g: &mut Game, ai: &mut LaikaAI) {
    let scale = g.scale;
    let my = ai.my_tank;
    ai.my_actions.clear();
    let fx = (g.tanks[my].x / scale).floor() as i64;
    let fy = (g.tanks[my].y / scale).floor() as i64;
    let goal = ai.my_goal.clone();

    match goal.kind {
        GoalKind::ShootAfter { target } => {
            let mt = g.tanks[my];
            let mut best_angle = mt.rotation;
            let mut found = false;
            let mut best_time = C::BULLETLIFETIME as f64;
            let mut closest = C::MOVIEWIDTH + C::MOVIEHEIGHT;
            let mut angle = mt.rotation;

            // Direct line of sight is checked first, geometrically rather than
            // ballistically.
            let dx = g.tanks[target].x - mt.x;
            let dy = g.tanks[target].y - mt.y;
            let d = (dx * dx + dy * dy).sqrt();
            let col = if d > 0.0 {
                check_path_for_collision(g, mt.x, mt.y, dx / d, dy / d, 1, d.ceil(), d.ceil())
            } else {
                None
            };
            if col.is_none() {
                found = true;
                closest = 0.0;
                if dx != 0.0 {
                    best_angle =
                        (if dx > 0.0 { 90.0 } else { -90.0 }) + ((dy / dx).atan() * 180.0) / PI;
                } else if dy > 0.0 {
                    best_angle = 180.0;
                } else if dy < 0.0 {
                    best_angle = 0.0;
                } else {
                    best_angle = angle;
                }
            }

            if !found {
                // Probe three angles at widening offsets, flipping side at random.
                for k in 1..=3 {
                    let res = ai.shot(g, angle);
                    if res.outcome == ShotOutcome::Hit {
                        found = true;
                        if res.time < best_time {
                            best_time = res.time;
                            closest = 0.0;
                            best_angle = angle;
                        }
                    } else if res.outcome == ShotOutcome::Nothing && !found {
                        if res.closest < closest {
                            closest = res.closest;
                            best_angle = angle;
                        }
                    }
                    let kk = (k * k) as f64;
                    if g.rng.random() < 0.5 {
                        angle += C::AIM_ANGLE_STEP * kk;
                    } else {
                        angle -= C::AIM_ANGLE_STEP * kk;
                    }
                    if angle < -180.0 {
                        angle = 360.0 + angle;
                    }
                    if angle > 180.0 {
                        angle -= 360.0;
                    }
                }
            }

            if found || closest < ai.max_closest_distance {
                ai.my_actions.push(Action::FireWeapon { delay: 5.0 });
                ai.my_actions.push(Action::TurnTo { angle: best_angle });
            } else if best_angle != mt.rotation {
                ai.my_actions.push(Action::TurnTo { angle: best_angle });
            } else {
                let mut a = mt.rotation + 180.0;
                if a > 180.0 {
                    a -= 360.0;
                }
                ai.my_actions.push(Action::TurnTo { angle: a });
            }
        }

        GoalKind::DriveTo { x, y } => {
            if let Some(dm) = g.dist_map(fx, fy).cloned() {
                let path =
                    shortest_path_with_distances(&g.maze, &dm, fx as usize, fy as usize, x, y);
                push_actions_to_follow_path(ai, scale, &path);
            }
        }

        GoalKind::RunAway { ref summed, sw, sh } => {
            // The undersized field is walked through a shim that reports NaN
            // outside its (w-1) x (h-1) extent, exactly as JS did.
            let path = follow_gradient_undersized(g, summed, sw, sh, fx as usize, fy as usize, 5);
            push_actions_to_follow_path(ai, scale, &path);
        }

        GoalKind::BackAway => {
            ai.my_actions.push(Action::DriveToPos {
                x: (fx as f64 + 0.5) * scale,
                y: (fy as f64 + 0.5) * scale,
                can_reverse: false,
            });
            let mt = g.tanks[my];
            let grid = &g.wall_grid;
            let front = expanded_hit_check(grid, &mt, &HIT_POINTS_FRONT, 1.1);
            let rear = expanded_hit_check(grid, &mt, &HIT_POINTS_REAR, 1.1);
            let left = || expanded_hit_check(grid, &mt, &HIT_POINTS_LEFT, 1.3000000000000005);
            if front {
                if rear {
                    let dir = if left() { Dir::Left } else { Dir::Right };
                    ai.my_actions.push(Action::BackupAndTurn { dist: 5.0, dir });
                } else {
                    ai.my_actions.push(Action::Backup { dist: 3.0 });
                }
            } else if rear {
                if front {
                    let dir = if left() { Dir::Left } else { Dir::Right };
                    ai.my_actions.push(Action::BackupAndTurn { dist: 5.0, dir });
                } else {
                    ai.my_actions.push(Action::Forward { dist: 3.0 });
                }
            } else {
                ai.my_actions.push(Action::Backup { dist: 3.0 });
            }
        }

        GoalKind::DodgeBullet {
            x,
            y,
            closest,
            dist,
            t,
            dir,
            max_time,
            max_dist,
        } => {
            let bx = (x / scale).floor() as i64;
            let by = (y / scale).floor() as i64;
            let path = match g.dist_map(bx, by).cloned() {
                Some(dm) => follow_gradient_with_distances_and_dead_ends(
                    &g.maze,
                    &dm,
                    &g.dead_ends,
                    fx as usize,
                    fy as usize,
                    5,
                ),
                None => Vec::new(),
            };
            let close_call = t < max_time / 3.0 && dist < max_dist / 5.0;

            if close_call || path.len() <= 1 {
                // No time or nowhere to run: turn side-on to the incoming line
                // so the tank presents its narrowest profile.
                let mt = g.tanks[my];
                let cur = mt.rotation;
                let mut a = if dir.0 != 0.0 {
                    (if dir.0 > 0.0 { 90.0 } else { -90.0 }) + ((dir.1 / dir.0).atan() * 180.0) / PI
                } else if dir.1 > 0.0 {
                    180.0
                } else if dir.1 < 0.0 {
                    0.0
                } else {
                    cur
                };
                if (a - cur).abs() > 90.0 && (a - cur).abs() < 270.0 {
                    a += 180.0;
                    if a > 180.0 {
                        a -= 360.0;
                    }
                }
                a = js_round(a / C::AIM_ANGLE_STEP) * C::AIM_ANGLE_STEP;
                ai.my_actions.push(Action::TurnTo { angle: a });

                if dist < scale / 4.0 {
                    // Point blank: step sideways off the line entirely.
                    let dl = (dir.0 * dir.0 + dir.1 * dir.1).sqrt();
                    if dl > 0.0 {
                        let perp = (-dir.1 / dl, dir.0 / dl);
                        let p1 = (
                            closest.0 + (perp.0 * scale) / 2.0,
                            closest.1 + (perp.1 * scale) / 2.0,
                        );
                        let p2 = (
                            closest.0 - (perp.0 * scale) / 2.0,
                            closest.1 - (perp.1 * scale) / 2.0,
                        );
                        let d1 = (mt.x - p1.0).hypot(mt.y - p1.1);
                        let d2 = (mt.x - p2.0).hypot(mt.y - p2.1);
                        let target = if d1 < d2 { p1 } else { p2 };
                        ai.my_actions.push(Action::DriveToPos {
                            x: target.0,
                            y: target.1,
                            can_reverse: true,
                        });
                    }
                }
            } else {
                push_actions_to_follow_path(ai, scale, &path);
            }
            try_to_retaliate(g, ai);
        }

        GoalKind::Idle => {
            ai.my_actions.push(Action::Idle);
        }
    }
}

/// `run_away` climbs a field that is one row and column short of the maze.
/// Reads outside it are NaN, so the walk never leaves the undersized region.
fn follow_gradient_undersized(
    g: &Game,
    summed: &[f64],
    sw: usize,
    sh: usize,
    startx: usize,
    starty: usize,
    max_length: i64,
) -> Vec<(usize, usize)> {
    let (w, h) = (g.maze.w, g.maze.h);
    let mut padded = vec![f64::NAN; w * h];
    for x in 0..sw {
        for y in 0..sh {
            padded[x * h + y] = summed[x * sh + y];
        }
    }
    follow_gradient_with_distances_and_dead_ends(
        &g.maze,
        &padded,
        &g.dead_ends,
        startx,
        starty,
        max_length,
    )
}

// ------------------------------------------------ phase 3: drive the tank

pub fn set_input_to_do_actions(g: &mut Game, ai: &mut LaikaAI) {
    let scale = g.scale;
    let my = ai.my_tank;
    let fx = (g.tanks[my].x / scale).floor() as i64;
    let fy = (g.tanks[my].y / scale).floor() as i64;

    let mut fraction = 1.0f64;
    let old_stack_length = ai.my_actions.len();
    // Pop the top action and put it back if it still has work left.
    if let Some(action) = ai.my_actions.pop() {
        match action {
            Action::DriveToField { x, y } => {
                let mt = g.tanks[my];
                if (mt.x - (x as f64 + 0.5) * scale).abs() > scale / 3.0
                    || (mt.y - (y as f64 + 0.5) * scale).abs() > scale / 3.0
                {
                    ai.my_actions.push(action);
                }
            }
            Action::TurnTo { angle } => {
                // Raw, unnormalised comparison - original quirk.
                if (g.tanks[my].rotation - angle).abs() >= g.tanks[my].turn_speed {
                    ai.my_actions.push(action);
                }
            }
            Action::FireWeapon { delay } => {
                if delay > 1e-9 {
                    ai.my_actions.push(Action::FireWeapon { delay: delay - C::STEP_25 });
                }
            }
            Action::DriveToPos { x, y, .. } => {
                let mt = g.tanks[my];
                if (mt.x - x).abs() > scale / 4.0 || (mt.y - y).abs() > scale / 4.0 {
                    ai.my_actions.push(action);
                }
            }
            Action::ForwardAndTurn { dist, dir } => {
                // Source fall-through decrements twice, including odd counters.
                let left = (dist as f64 / 2.0).ceil();
                if left > 1e-9 {
                    fraction = (left / C::STEP_25).min(1.0);
                    ai.my_actions.push(Action::ForwardAndTurnTime {left:left-C::STEP_25,dir});
                }
            }
            Action::ForwardAndTurnTime { left, dir } => {
                if left > 1e-9 {
                    fraction = (left / C::STEP_25).min(1.0);
                    ai.my_actions.push(Action::ForwardAndTurnTime {left:left-C::STEP_25,dir});
                }
            }
            Action::Forward { dist } => {
                if dist > 1e-9 {
                    fraction = (dist / C::STEP_25).min(1.0);
                    ai.my_actions.push(Action::Forward { dist: dist - C::STEP_25 });
                }
            }
            Action::Backup { dist } => {
                if dist > 1e-9 {
                    fraction = (dist / C::STEP_25).min(1.0);
                    ai.my_actions.push(Action::Backup { dist: dist - C::STEP_25 });
                }
            }
            Action::BackupAndTurn { dist, dir } => {
                if dist > 1e-9 {
                    fraction = (dist / C::STEP_25).min(1.0);
                    ai.my_actions.push(Action::BackupAndTurn {
                        dist: dist - C::STEP_25,
                        dir,
                    });
                }
            }
            Action::Idle => {
                ai.my_actions.push(action);
            }
        }
    }

    // A completed action can reveal a timed action without decrementing it.
    // In25Hz source that first interval lasts40ms; this tick only lasts1/60s.
    // Keep the remaining fraction rather than losing time at every transition.
    if ai.my_actions.len() < old_stack_length {
        if let Some(action) = ai.my_actions.last_mut() {
            let extra = 1.0-C::STEP_25;
            match action {
                Action::FireWeapon { delay } => *delay += extra,
                Action::Forward { dist } | Action::Backup { dist }
                | Action::ForwardAndTurnTime { left: dist, .. } | Action::BackupAndTurn { dist, .. } => *dist += extra,
                Action::ForwardAndTurn {dist,dir} => {
                    *action=Action::ForwardAndTurnTime {left:(*dist as f64/2.0).ceil()+extra,dir:*dir};
                }
                _ => {}
            }
        }
    }
    // Whatever is on top now decides this frame's input.
    let top = ai.my_actions.last().copied();
    let action = match top {
        None => {
            let t = &mut g.tanks[my];
            t.turn_left = false;
            t.turn_right = false;
            t.forward = false;
            t.backup = false;
            t.fire = false;
            ai.my_goal.period = 0.0;
            return;
        }
        Some(a) => a,
    };

    match action {
        Action::DriveToField { x, y } => {
            let cur = g.tanks[my].rotation;
            let target = if fx > x as i64 {
                -90.0
            } else if fx < x as i64 {
                90.0
            } else if fy > y as i64 {
                0.0
            } else if fy < y as i64 {
                180.0
            } else {
                cur
            };
            ai.turn_toward(g, target, cur);
            let backwards = (target - cur).abs() > 90.0 && (target - cur).abs() < 270.0;
            let t = &mut g.tanks[my];
            t.forward = !backwards;
            t.backup = false;
            t.fire = false;
        }

        Action::TurnTo { angle } => {
            let cur = g.tanks[my].rotation;
            ai.turn_toward(g, angle, cur);
            let t = &mut g.tanks[my];
            t.forward = false;
            t.backup = false;
            t.fire = false;
        }

        Action::FireWeapon { .. } => {
            let t = &mut g.tanks[my];
            t.turn_left = false;
            t.turn_right = false;
            t.forward = false;
            t.backup = false;
            t.fire = true;
        }

        Action::DriveToPos { x, y, can_reverse } => {
            let mt = g.tanks[my];
            let cur = mt.rotation;
            let mut reverse = false;
            let dx = x - mt.x;
            let dy = y - mt.y;
            let mut target = if dx != 0.0 {
                (if dx > 0.0 { 90.0 } else { -90.0 }) + ((dy / dx).atan() * 180.0) / PI
            } else if dy > 0.0 {
                180.0
            } else if dy < 0.0 {
                0.0
            } else {
                cur
            };
            target = C::AIM_ANGLE_STEP * js_round(target / C::AIM_ANGLE_STEP);
            if can_reverse && (target - cur).abs() > 90.0 && (target - cur).abs() < 270.0 {
                reverse = true;
                target += 180.0;
                if target > 180.0 {
                    target -= 360.0;
                }
            }
            // Turning here has a dead zone, unlike turn_toward, so the tank
            // stops wobbling once it is roughly on heading.
            let (tl, tr) = if target > cur {
                if (target - cur).abs() > 180.0 {
                    ((target - cur).abs() < 360.0 - mt.turn_speed, false)
                } else {
                    (false, (target - cur).abs() > mt.turn_speed)
                }
            } else if target < cur {
                if (target - cur).abs() > 180.0 {
                    (false, (target - cur).abs() < 360.0 - mt.turn_speed)
                } else {
                    ((target - cur).abs() > mt.turn_speed, false)
                }
            } else {
                (false, false)
            };
            let t = &mut g.tanks[my];
            t.turn_left = tl;
            t.turn_right = tr;
            if (target - cur).abs() > 45.0 && (target - cur).abs() < 315.0 {
                t.forward = false;
                t.backup = false;
            } else {
                t.forward = !reverse;
                t.backup = reverse;
            }
            t.fire = false;
        }

        Action::Forward { .. } => {
            let t = &mut g.tanks[my];
            t.turn_left = false;
            t.turn_right = false;
            t.forward = true;
            t.backup = false;
            t.fire = false;
        }

        Action::ForwardAndTurn { dir, .. } | Action::ForwardAndTurnTime { dir, .. } => {
            let t = &mut g.tanks[my];
            t.turn_left = dir == Dir::Left;
            t.turn_right = dir == Dir::Right;
            t.forward = true;
            t.backup = false;
            t.fire = false;
        }

        Action::Backup { .. } => {
            let t = &mut g.tanks[my];
            t.turn_left = false;
            t.turn_right = false;
            t.forward = false;
            t.backup = true;
            t.fire = false;
        }

        Action::BackupAndTurn { dir, .. } => {
            let t = &mut g.tanks[my];
            t.turn_left = dir == Dir::Left;
            t.turn_right = dir == Dir::Right;
            t.forward = false;
            t.backup = true;
            t.fire = false;
        }

        Action::Idle => {
            let t = &mut g.tanks[my];
            t.turn_left = false;
            t.turn_right = false;
            t.forward = false;
            t.backup = false;
            t.fire = false;
        }
    }
    if fraction < 1.0 {
        let t = &mut g.tanks[my];
        t.forward_amount = Some(fraction);
        t.backup_amount = Some(fraction);
        t.turn_left_amount = Some(fraction);
        t.turn_right_amount = Some(fraction);
    }

}

/// The three phases, in order — the JS `Tank.update` AI hook.
pub fn laika_step(g: &mut Game, ai: &mut LaikaAI) {
    let my = ai.my_tank;
    g.tanks[my].forward_amount = None;
    g.tanks[my].backup_amount = None;
    g.tanks[my].turn_left_amount = None;
    g.tanks[my].turn_right_amount = None;
    if make_decisions_and_update_goal(g, ai) {
        decide_actions_to_achieve_goal(g, ai);
    }
    set_input_to_do_actions(g, ai);
}
