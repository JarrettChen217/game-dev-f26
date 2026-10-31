//! Play-only bridge over the retained Training/Game; no second simulator.
#![allow(dead_code)]
#[path="lib.rs"] pub mod training;
pub use training::{constants,game,laika,maze,rng,ballistics,duel,score,sandbox,risk,hybrid_obs};

mod play_fixtures;

pub struct Play {pub env:training::Training,pub human:bool,pub fixture:u32}
impl Play {
    pub fn new(seed:u32,human:bool)->Self {
        let mut env=training::Training::new(seed);
        if human {env.game.ai_enabled[1]=false;env.game.ais[1]=None;}
        Self{env,human,fixture:0}
    }
    pub fn fixture(seed:u32,kind:u32)->Option<Self> {
        if !(1..=6).contains(&kind) {return None;}
        let mut p=Self::new(seed,true);
        if kind>1 {p.env.game=play_fixtures::lesson(seed,kind-1);}
        let g=&mut p.env.game;
        g.ai_enabled=vec![false,false];g.ais=vec![None,None];g.weapons_disabled[0]=true;
        g.tanks[0].alive=kind==4;g.alive_count=if kind==4 {2}else{1};
        g.end_count=-1;g.reset_count=-1;g.frozen=false;
        p.fixture=kind;Some(p)
    }
    // Play-only ownership switch. Training::new/step and the training ABI stay unchanged.
    pub fn set_opponent(&mut self,native_laika:bool)->bool {
        if self.env.game.frame!=0 {return false;}
        let g=&mut self.env.game;
        g.ai_enabled[0]=native_laika;
        g.ais[0]=if native_laika {Some(laika::LaikaAI::new(g.scale,0))} else {None};
        true
    }
    pub fn step(&mut self,actor:u16,human:u16)->i32 {
        if actor>=18 || human>=18 {return -1;}
        if self.env.outcome!=0 {return 0;}
        if self.human {
            let a=score::CANDIDATES[human as usize];let t=&mut self.env.game.tanks[1];
            t.backup=a[0]==0;t.forward=a[0]==2;t.turn_left=a[1]==0;t.turn_right=a[1]==2;t.fire=a[2]==1;
            t.forward_amount=None;t.backup_amount=None;t.turn_left_amount=None;t.turn_right_amount=None;
        }
        if self.fixture!=0 {
            self.env.game.step();
            self.env.outcome=if self.env.game.frozen {4}else{0};
            1
        } else {self.env.step(actor)}
    }
}
#[no_mangle] pub extern "C" fn kf60_play_new(seed:u32,human:u32)->*mut Play {
    if human>1 {return std::ptr::null_mut();}
    Box::into_raw(Box::new(Play::new(seed,human==1)))
}
#[no_mangle] pub extern "C" fn kf60_play_fixture(seed:u32,kind:u32)->*mut Play {
    Play::fixture(seed,kind).map(|p|Box::into_raw(Box::new(p))).unwrap_or(std::ptr::null_mut())
}
#[no_mangle] pub unsafe extern "C" fn kf60_play_opponent(p:*mut Play,kind:u32)->i32 {
    if p.is_null()||kind>1 {return -1;}
    (*p).set_opponent(kind==1) as i32
}
#[no_mangle] pub unsafe extern "C" fn kf60_play_free(p:*mut Play) {if !p.is_null(){drop(Box::from_raw(p));}}
#[no_mangle] pub unsafe extern "C" fn kf60_play_step(p:*mut Play,a:u16,h:u16)->i32 {
    if p.is_null(){-1}else{(*p).step(a,h)}
}
#[no_mangle] pub unsafe extern "C" fn kf60_play_read(p:*const Play,v:*mut f32,m:*mut u8,i:*mut f64) {
    if !p.is_null(){training::kf60_train_read(&(*p).env,v,m,i);}
}
// Render only: the existing source60 snapshot layout, from this exact Game.
#[no_mangle] pub unsafe extern "C" fn kf60_play_snapshot(p:*const Play,out:*mut f64,capacity:usize)->usize {
    if p.is_null(){return 0;}let e=&(*p).env;let g=&e.game;
    let render_len=138+g.walls.len()*4+g.tanks.len()*6+g.bullets.len()*2;
    let mut r=vec![0.;8+render_len+24+g.bullets.len()*10];
    r[..8].copy_from_slice(&[1.,render_len as f64,24.,(g.bullets.len()*10) as f64,
        g.laika_calls as f64,g.laika_nanos as f64,g.frame as f64,0.]);
    let h=&mut r[8..8+render_len];
    h[0]=g.maze.w as f64;h[1]=g.maze.h as f64;h[2]=g.scale;h[3]=g.wall_half_t;
    h[5]=g.walls.len() as f64;h[6]=g.tanks.len() as f64;h[7]=g.bullets.len() as f64;
    h[8]=g.frame as f64;h[9]=g.round_number as f64;h[10]=g.scores[0] as f64;h[11]=g.scores[1] as f64;
    h[12]=g.alive_count as f64;h[13]=g.end_count as f64;h[14]=(g.frozen||e.outcome!=0) as u8 as f64;
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
        s[4]=(b.owner==1) as u8 as f64;s[5]=b.has_bounced as u8 as f64;s[6]=b.lifetime as f64/600.;
    }
    if !out.is_null()&&capacity>=r.len(){std::ptr::copy_nonoverlapping(r.as_ptr(),out,r.len());}r.len()
}

// Read-only host facts, separate from the unchanged training observation/action ABI.
#[no_mangle] pub unsafe extern "C" fn kf60_play_facts(p:*const Play,out:*mut f64,cap:usize)->usize {
    if p.is_null(){return 0;}let p=&*p;let g=&p.env.game;
    let expired:Vec<u32>=g.events.iter().filter_map(|e|if let game::Event::Expire(id)=e {Some(*id)}else{None}).collect();
    let mut r=vec![1.,g.bullets.len() as f64,g.hit_records.len() as f64,expired.len() as f64,
        g.round_shots_fired[1] as f64,g.tanks[1].trigger_released as u8 as f64,p.fixture as f64,
        g.ai_enabled[0] as u8 as f64,g.ai_enabled[1] as u8 as f64];
    for b in &g.bullets {r.extend_from_slice(&[b.id as f64,b.owner as f64,b.x,b.y,b.x_speed,b.y_speed,
        b.lifetime as f64,b.has_bounced as u8 as f64,b.just_created as u8 as f64]);}
    for h in &g.hit_records {r.extend_from_slice(&[h.bullet_id as f64,h.owner as f64,h.victim as f64,h.has_bounced as u8 as f64]);}
    r.extend(expired.iter().map(|x|*x as f64));
    if !out.is_null()&&cap>=r.len(){std::ptr::copy_nonoverlapping(r.as_ptr(),out,r.len());}r.len()
}
