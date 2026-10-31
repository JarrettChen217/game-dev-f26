//! Native60Hz adaptation of Cichlider's MIT-licensed Killfield core.
//! Original25Hz files remain unchanged in original_laika/source.
#![allow(dead_code)]
mod constants;
mod game;
mod laika;
#[path="../../original_laika/source/maze.rs"] mod maze;
#[path="../../original_laika/source/rng.rs"] mod rng;
#[path="../../original_laika/source/ballistics.rs"] mod ballistics;

use game::Game;
pub struct Engine { game: Game, step_nanos: u64 }

#[no_mangle]
pub extern "C" fn kf60_new(seed: u32) -> *mut Engine {
    Box::into_raw(Box::new(Engine{game:Game::with_ai(seed,2,&[0]),step_nanos:0}))
}
#[no_mangle]
pub unsafe extern "C" fn kf60_free(handle: *mut Engine) {
    if !handle.is_null() {drop(Box::from_raw(handle));}
}

// All output is observed state/diagnostics. No policy internals cross the ABI.
unsafe fn snapshot(e:&Engine,out:*mut f64,capacity:usize)->usize {
    let g=&e.game;
    let render_len=138+g.walls.len()*4+g.tanks.len()*6+g.bullets.len()*2;
    let mut r=vec![0.;8+render_len+24+g.bullets.len()*10];
    r[..8].copy_from_slice(&[1.,render_len as f64,24.,(g.bullets.len()*10) as f64,
        g.laika_calls as f64,g.laika_nanos as f64,g.frame as f64,e.step_nanos as f64]);
    let h=&mut r[8..8+render_len];
    h[0]=g.maze.w as f64;h[1]=g.maze.h as f64;h[2]=g.scale;h[3]=g.wall_half_t;
    h[5]=g.walls.len() as f64;h[6]=g.tanks.len() as f64;h[7]=g.bullets.len() as f64;
    h[8]=g.frame as f64;h[9]=g.round_number as f64;h[10]=g.scores[0] as f64;h[11]=g.scores[1] as f64;
    h[12]=g.alive_count as f64;h[13]=g.end_count as f64;h[14]=g.frozen as u8 as f64;
    let mut k=138;
    for w in g.walls.iter() {h[k..k+4].copy_from_slice(w);k+=4;}
    for t in &g.tanks {h[k..k+6].copy_from_slice(&[t.x,t.y,t.rotation,t.alive as u8 as f64,t.number as f64,t.display_scale]);k+=6;}
    for b in &g.bullets {h[k]=b.x;h[k+1]=b.y;k+=2;}
    let base=8+render_len;
    for (i,seat) in [1usize,0].iter().enumerate() {
        let t=&g.tanks[*seat];let s=&mut r[base+i*12..base+(i+1)*12];
        s[7]=(g.settings_max_bullets-t.bullets_fired) as f64/g.settings_max_bullets as f64;
        s[8]=g.weapon_ready(*seat) as u8 as f64;s[9]=t.alive as u8 as f64;
        s[10]=t.hit_something as u8 as f64;s[11]=t.wall_sliding as u8 as f64;
    }
    let angle=(g.tanks[1].rotation-90.)*constants::DEG;
    for (i,b) in g.bullets.iter().enumerate() {
        let s=&mut r[base+24+i*10..base+24+(i+1)*10];
        s[2]=(b.x_speed*angle.cos()+b.y_speed*angle.sin())/(0.5*g.scale);
        s[3]=(-b.x_speed*angle.sin()+b.y_speed*angle.cos())/(0.5*g.scale);
        s[4]=(b.owner==1) as u8 as f64;s[5]=b.has_bounced as u8 as f64;
        s[6]=b.lifetime as f64/600.;
    }
    if !out.is_null() && capacity>=r.len() {std::ptr::copy_nonoverlapping(r.as_ptr(),out,r.len());}
    r.len()
}

#[no_mangle]
pub unsafe extern "C" fn kf60_snapshot(handle:*const Engine,out:*mut f64,capacity:usize)->usize {
    if handle.is_null() {return 0;}snapshot(&*handle,out,capacity)
}
#[no_mangle]
pub unsafe extern "C" fn kf60_step(handle:*mut Engine,throttle:i32,turn:i32,fire:i32,out:*mut f64,capacity:usize)->usize {
    if handle.is_null() {return 0;}
    let e=&mut *handle;
    if !e.game.frozen {
        let t=&mut e.game.tanks[1];
        t.forward=throttle>0;t.backup=throttle<0;t.turn_left=turn<0;t.turn_right=turn>0;t.fire=fire!=0;
        let start=std::time::Instant::now();e.game.step();e.step_nanos+=start.elapsed().as_nanos() as u64;
    }
    snapshot(e,out,capacity)
}
