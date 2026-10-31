//!Source60 training interface: one authoritative Game, no optimizer or renderer.
#![allow(dead_code)]
#[path="../../source/constants.rs"] pub mod constants;
#[path="../../source/game.rs"] pub mod game;
#[path="../../source/laika.rs"] pub mod laika;
#[path="../../../original_laika/source/maze.rs"] pub mod maze;
#[path="../../../original_laika/source/rng.rs"] pub mod rng;
#[path="../../../original_laika/source/ballistics.rs"] pub mod ballistics;
pub mod duel;
pub mod score;
pub mod sandbox;
pub mod risk;
pub mod hybrid_obs;
#[cfg(not(target_arch="wasm32"))]
pub mod batch;

use game::{Game,Event};
use hybrid_obs::{DuelObservation,SeatHistory,DODGE_OFFSET};

pub struct Training {
    pub game:Game,
    pub history:SeatHistory,
    pub previous:[[f64;3];2],
    pub boxes:Vec<[f64;4]>,
    pub observation:DuelObservation,
    pub outcome:u8,
    pub reward:f64,
    pub shots:u32,
    pub hits:u32,
}
#[no_mangle] pub extern "C" fn kf60_train_schema()->u32 {hybrid_obs::OBS_SCHEMA_VERSION}
#[no_mangle] pub extern "C" fn kf60_train_features()->u32 {hybrid_obs::OBS_DIM as u32}
#[no_mangle] pub extern "C" fn kf60_train_masks()->u32 {hybrid_obs::BULLET_SLOTS as u32}
#[no_mangle] pub extern "C" fn kf60_train_actions()->u32 {duel::DUEL_ACTIONS as u32}
fn poses(g:&Game)->[[f64;3];2] {
    [[g.tanks[0].x,g.tanks[0].y,g.tanks[0].rotation],
     [g.tanks[1].x,g.tanks[1].y,g.tanks[1].rotation]]
}
impl Training {
    pub fn new(seed:u32)->Self {
        let game=Game::with_ai(seed,2,&[1]);
        let t=game.wall_half_t;
        let boxes=game.walls.iter().map(|&[x1,y1,x2,y2]|
            [x1.min(x2)-t,y1.min(y2)-t,x1.max(x2)+t,y1.max(y2)+t]).collect();
        let previous=poses(&game);
        let mut env=Self{game,history:SeatHistory::default(),previous,boxes,
            observation:DuelObservation::default(),outcome:0,reward:0.,shots:0,hits:0};
        env.encode();env
    }
    pub fn encode(&mut self) {
        self.encode_instrumented::<false>(&mut [0.;5]);
    }
    fn encode_instrumented<const PROFILE:bool>(&mut self,profile:&mut [f64;5]) {
        let start=if PROFILE {Some(std::time::Instant::now())} else {None};
        hybrid_obs::encode(&self.game,0,&self.previous,&self.boxes,&self.history,&mut self.observation);
        if let Some(start)=start {profile[1]+=start.elapsed().as_secs_f64();}
        let start=if PROFILE {Some(std::time::Instant::now())} else {None};
        let dodge=hybrid_obs::reconstructed_dodge(&self.game,0);
        self.observation.values[DODGE_OFFSET..DODGE_OFFSET+9].copy_from_slice(&dodge);
        if let Some(start)=start {profile[2]+=start.elapsed().as_secs_f64();}
    }
    pub fn step(&mut self,action:u16)->i32 {
        self.step_instrumented::<false>(action,&mut [0.;5])
    }
    fn step_profiled(&mut self,action:u16,profile:&mut [f64;5])->i32 {
        let start=std::time::Instant::now();
        let result=self.step_instrumented::<true>(action,profile);
        profile[4]+=start.elapsed().as_secs_f64();
        result
    }
    fn step_instrumented<const PROFILE:bool>(&mut self,action:u16,profile:&mut [f64;5])->i32 {
        if action>=18 {return -1;}
        if self.outcome!=0 {return 0;}
        self.previous=poses(&self.game);
        self.history.record(action);
        let a=score::CANDIDATES[action as usize];let t=&mut self.game.tanks[0];
        t.backup=a[0]==0;t.forward=a[0]==2;t.turn_left=a[1]==0;t.turn_right=a[1]==2;t.fire=a[2]==1;
        t.forward_amount=None;t.backup_amount=None;t.turn_left_amount=None;t.turn_right_amount=None;
        let start=if PROFILE {Some(std::time::Instant::now())} else {None};
        let events=self.game.step();
        if let Some(start)=start {profile[0]+=start.elapsed().as_secs_f64();}
        self.shots+=events.iter().filter(|e|matches!(e,Event::Fire(0))).count() as u32;
        self.hits+=events.iter().filter(|e|matches!(e,Event::Hit{owner:0,victim:1})).count() as u32;
        let frames=self.game.frame as u32;
        self.outcome=if self.game.frozen {
            match (self.game.tanks[0].alive,self.game.tanks[1].alive) {
                (true,false)=>1,(false,true)=>2,(false,false)=>3,_=>4}
        } else if (frames>=duel::DUEL_FRAMES && self.game.end_count<0)
               || frames>=duel::DUEL_FRAMES+duel::DUEL_GRACE_FRAMES {4} else {0};
        self.reward=duel::terminal_reward(self.outcome,frames,self.history.changes);
        self.encode_instrumented::<PROFILE>(profile);1
    }
    pub fn info(&self)->[f64;24] {
        let g=&self.game;let a=&g.tanks[0];let b=&g.tanks[1];
        [1.,g.frame as f64,self.outcome as f64,self.reward,self.shots as f64,self.hits as f64,
         self.history.changes as f64,a.x,a.y,a.rotation,a.alive as u8 as f64,
         b.x,b.y,b.rotation,b.alive as u8 as f64,g.ai_enabled[0] as u8 as f64,
         g.ai_enabled[1] as u8 as f64,g.laika_calls as f64,g.end_count as f64,g.frozen as u8 as f64,
         self.history.actions[0].map(|a|a as f64).unwrap_or(-1.),
         self.history.frames as f64,self.history.idle_streak as f64,60.]
    }
}
#[no_mangle] pub extern "C" fn kf60_train_new(seed:u32)->*mut Training {Box::into_raw(Box::new(Training::new(seed)))}
#[no_mangle] pub unsafe extern "C" fn kf60_train_free(p:*mut Training) {if !p.is_null(){drop(Box::from_raw(p));}}
#[no_mangle] pub unsafe extern "C" fn kf60_train_step(p:*mut Training,a:u16)->i32 {if p.is_null(){-1}else{(*p).step(a)}}
#[no_mangle] pub unsafe extern "C" fn kf60_train_read(p:*const Training,v:*mut f32,m:*mut u8,i:*mut f64) {
    if p.is_null(){return;}let e=&*p;
    std::ptr::copy_nonoverlapping(e.observation.values.as_ptr(),v,1028);
    for n in 0..10 {*m.add(n)=e.observation.bullet_mask[n] as u8;}
    std::ptr::copy_nonoverlapping(e.info().as_ptr(),i,24);
}
