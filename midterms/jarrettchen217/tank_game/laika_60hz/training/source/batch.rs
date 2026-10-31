//! Independent native sampler slots with scoped, disjoint worker chunks.
//!
//! All i32 ABI calls return 0 on success and -1 for invalid arguments. Callers
//! own correctly sized, non-overlapping buffers and serialize calls per handle.
//! Profile values are cumulative sums of per-slot worker elapsed seconds, not
//! wall time: workers overlap. Fields are game step, observation encode (without
//! dodge), dodge reconstruction, reset, and total slot step. Construction and
//! reads are excluded; reset is separate from total slot step.

use super::Training;
use std::time::Instant;

pub struct TrainingBatch {
    pub(crate) environments:Vec<Training>,
    episodes:Vec<u32>,
    profiles:Vec<[f64;5]>,
    seed:u32,
    threads:usize,
}

fn slot_seed(seed:u32,index:usize,episode:u32)->u32 {
    seed.wrapping_add((index as u32).wrapping_mul(0x9e37_79b9))
        .wrapping_add(episode.wrapping_mul(0x85eb_ca6b))
}

fn step_chunk(envs:&mut [Training],profiles:&mut [[f64;5]],actions:&[u16]) {
    for ((env,profile),&action) in envs.iter_mut().zip(profiles).zip(actions) {
        env.step_profiled(action,profile);
    }
}

fn reset_chunk(envs:&mut [Training],episodes:&mut [u32],profiles:&mut [[f64;5]],
               seed:u32,base:usize) {
    for (offset,((env,episode),profile)) in envs.iter_mut().zip(episodes).zip(profiles).enumerate() {
        if env.outcome==0 {continue;}
        let start=Instant::now();
        *episode=episode.wrapping_add(1);
        *env=Training::new(slot_seed(seed,base+offset,*episode));
        profile[3]+=start.elapsed().as_secs_f64();
    }
}

impl TrainingBatch {
    fn new(count:usize,seed:u32,threads:usize)->Self {
        Self {
            environments:(0..count).map(|i|Training::new(slot_seed(seed,i,0))).collect(),
            episodes:vec![0;count],profiles:vec![[0.;5];count],seed,threads,
        }
    }

    fn step(&mut self,actions:&[u16])->i32 {
        // Validate the complete list before any slot, history, RNG or profile changes.
        if actions.len()!=self.environments.len() || actions.iter().any(|&a|a>=18) {return -1;}
        if self.threads==1 {
            step_chunk(&mut self.environments,&mut self.profiles,actions);
        } else {
            let chunk=self.environments.len().div_ceil(self.threads);
            std::thread::scope(|scope| {
                for ((envs,profiles),actions) in self.environments.chunks_mut(chunk)
                    .zip(self.profiles.chunks_mut(chunk)).zip(actions.chunks(chunk)) {
                    scope.spawn(move ||step_chunk(envs,profiles,actions));
                }
            });
        }
        0
    }

    fn reset_done(&mut self)->i32 {
        if !self.environments.iter().any(|env|env.outcome!=0) {return 0;}
        if self.threads==1 {
            reset_chunk(&mut self.environments,&mut self.episodes,&mut self.profiles,self.seed,0);
        } else {
            let chunk=self.environments.len().div_ceil(self.threads);
            let seed=self.seed;
            std::thread::scope(|scope| {
                for (block,((envs,episodes),profiles)) in self.environments.chunks_mut(chunk)
                    .zip(self.episodes.chunks_mut(chunk)).zip(self.profiles.chunks_mut(chunk)).enumerate() {
                    scope.spawn(move ||reset_chunk(envs,episodes,profiles,seed,block*chunk));
                }
            });
        }
        0
    }
}

#[no_mangle]
pub extern "C" fn kf60_vec_abi()->u32 {1}

#[no_mangle]
pub extern "C" fn kf60_vec_new(count:u32,seed:u32,threads:u32)->*mut TrainingBatch {
    if !(1..=128).contains(&count) || !matches!(threads,1|4|8|16) {return std::ptr::null_mut();}
    Box::into_raw(Box::new(TrainingBatch::new(count as usize,seed,threads as usize)))
}

#[no_mangle]
pub unsafe extern "C" fn kf60_vec_free(p:*mut TrainingBatch) {
    if !p.is_null() {drop(Box::from_raw(p));}
}

#[no_mangle]
pub unsafe extern "C" fn kf60_vec_step(p:*mut TrainingBatch,actions:*const u16)->i32 {
    if p.is_null() || actions.is_null() {return -1;}
    let env=&mut *p;
    env.step(std::slice::from_raw_parts(actions,env.environments.len()))
}

#[no_mangle]
pub unsafe extern "C" fn kf60_vec_reset_done(p:*mut TrainingBatch)->i32 {
    if p.is_null() {return -1;}
    (*p).reset_done()
}

/// Copy count*1028 f32 features, count*10 u8 masks and count*24 f64 info in slot order.
#[no_mangle]
pub unsafe extern "C" fn kf60_vec_read(p:*const TrainingBatch,features:*mut f32,
                                      masks:*mut u8,info:*mut f64)->i32 {
    if p.is_null() || features.is_null() || masks.is_null() || info.is_null() {return -1;}
    for (i,env) in (*p).environments.iter().enumerate() {
        std::ptr::copy_nonoverlapping(env.observation.values.as_ptr(),features.add(i*1028),1028);
        for j in 0..10 {*masks.add(i*10+j)=env.observation.bullet_mask[j] as u8;}
        std::ptr::copy_nonoverlapping(env.info().as_ptr(),info.add(i*24),24);
    }
    0
}

#[no_mangle]
pub unsafe extern "C" fn kf60_vec_profile(p:*const TrainingBatch,out:*mut f64)->i32 {
    if p.is_null() || out.is_null() {return -1;}
    let mut total=[0.;5];
    for profile in &(*p).profiles {
        for i in 0..5 {total[i]+=profile[i];}
    }
    std::ptr::copy_nonoverlapping(total.as_ptr(),out,5);
    0
}
