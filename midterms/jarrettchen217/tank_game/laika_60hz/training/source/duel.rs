//! Narrow reuse of the verified duel terminal reward, with explicit time units.
pub const DUEL_ACTIONS: usize = 18;
pub const DUEL_FRAMES: u32 = 1800;
pub const DUEL_GRACE_FRAMES: u32 = 300;
pub const WIN_FULL_FRAMES: u32 = 600;
pub const STYLE_MAX: f64 = 0.25;
pub const STYLE_ANCHOR_RATE: f64 = 0.13;

pub fn win_reward(frames: u32) -> f64 {
    if frames <= WIN_FULL_FRAMES {return 1.0;}
    let elapsed=frames.min(DUEL_FRAMES) as f64/WIN_FULL_FRAMES as f64;
    let span=(DUEL_FRAMES as f64/WIN_FULL_FRAMES as f64).ln();
    (1.0-0.5*elapsed.ln()/span).clamp(0.5,1.0)
}
pub fn style_bonus(changes:u32,frames:u32)->f64 {
    if frames<=1 {return STYLE_MAX;}
    let rate=changes as f64/((frames-1) as f64*crate::constants::STEP_25);
    if rate<=STYLE_ANCHOR_RATE {return STYLE_MAX;}
    let span=(1.0/STYLE_ANCHOR_RATE).ln();
    (STYLE_MAX*(1.0-(rate/STYLE_ANCHOR_RATE).ln()/span)).clamp(0.0,STYLE_MAX)
}
pub fn terminal_reward(outcome:u8,frames:u32,changes:u32)->f64 {
    let base=match outcome {1=>win_reward(frames),2|4=>-1.0,3=>0.0,_=>return 0.0};
    base+style_bonus(changes,frames)
}
