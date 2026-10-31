//! Host-only practice/lesson initial states. Physics stays in source Game::step.
use std::sync::Arc;
use super::{game,maze};

pub fn lesson(seed:u32,step:u32)->game::Game {
    let (w,h)=if step==1 {(6,2)}else{(8,6)};
    let mut g=game::Game::range_arena(seed,w,h);
    let mut m=maze::Maze{w,h,cells:vec![[1,0,0];w*h]};
    if step==2 {
        for x in 0..6 {m.cells[x*h+3][1]=1;}
        for y in 0..4 {m.cells[6*h+y][2]=1;}
    }
    g.maze=Arc::new(m);
    g.walls=Arc::new(maze::build_wall_segments(&g.maze,g.scale));
    g.wall_grid=Arc::new(maze::WallGrid::new(&g.walls,g.wall_half_t,g.scale));
    let reachable=maze::calc_reachable(&g.maze,0,0);
    g.reachable=Arc::new(reachable.cells);g.reachable_index=Arc::new(reachable.index);
    // No policy/planner uses this fixture; wall/grid/tank physics are the normal Game.
    let (x,y,heading)=match step {1=>(1.5,1.5,0.),2=>(1.,5.,0.),3=>(1.5,3.,0.),4=>(5.5,3.,0.),_=>(1.5,3.,30.)};
    g.tanks[1].x=x*g.scale;g.tanks[1].y=y*g.scale;g.tanks[1].rotation=heading+90.;
    g.tanks[0].x=4.5*g.scale;g.tanks[0].y=3.*g.scale;g.tanks[0].rotation=270.;
    g
}
