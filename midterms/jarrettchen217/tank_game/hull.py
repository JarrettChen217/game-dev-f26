"""Optional native-clock oriented hull geometry, shared by World and policies.

Reference Killfield base hull is81 long x61 wide (MIT attribution in notices).
Normalize its half diagonal to Tank radius: original art and circle defaults
stay intact. No reference movement/engine is imported. Native tick convention:
bounded collision-safe turn first, then exact swept fixed-orientation sliding.
"""
from math import ceil, cos, hypot, radians, sin

from tank_game.map import Rect
from tank_game.paths import Segment
from tank_game.physics import (
    CONTACT_GAP,
    MAX_CONTACTS,
    MoveResult,
    _slide,
    circle_clear,
    first_wall_contact,
)

NORM=hypot(40.5,30.5)
LENGTH_RATIO=40.5/NORM
WIDTH_RATIO=30.5/NORM
PROFILE={'id':'rectangle-v1','half_length_ratio':LENGTH_RATIO,'half_width_ratio':WIDTH_RATIO,
         'turn_convention':'bounded-turn-then-swept-translation',
         'body_pair':'conservative-circumcircle'}


def enabled(scene):
    return scene.get('collision_profile',{}).get('id')=='rectangle-v1'


def axes(heading):
    a=radians(heading);c,s=cos(a),sin(a)
    return (c,s),(-s,c)


def _extent(radius,heading,axis):
    u,v=axes(heading)
    return radius*(LENGTH_RATIO*abs(u[0]*axis[0]+u[1]*axis[1])+
                   WIDTH_RATIO*abs(v[0]*axis[0]+v[1]*axis[1]))


def lateral_extent(radius,heading,vx,vy):
    speed=hypot(vx,vy)
    return _extent(radius,heading,(-vy/speed,vx/speed)) if speed else radius


def rectangle_clear(x,y,radius,heading,walls,margin=0):
    for wall in walls:
        wx,wy=wall.x+wall.width/2,wall.y+wall.height/2
        separated=False
        for ax,ay in ((1,0),(0,1),*axes(heading)):
            reach=_extent(radius,heading,(ax,ay))+margin+abs(ax)*wall.width/2+abs(ay)*wall.height/2
            if abs((x-wx)*ax+(y-wy)*ay)>reach:
                separated=True;break
        if not separated:return False
    return True


def _sweep(x,y,radius,heading,dx,dy,wall):
    enter,leave=0.,1.
    normals=[]
    cx,cy=x-wall.x-wall.width/2,y-wall.y-wall.height/2
    for ax,ay in ((1,0),(0,1),*axes(heading)):
        reach=_extent(radius,heading,(ax,ay))+abs(ax)*wall.width/2+abs(ay)*wall.height/2
        q,v=cx*ax+cy*ay,dx*ax+dy*ay
        if abs(q)>=reach-1e-10 and q*v>=-1e-12:return None
        if abs(v)<1e-14:
            if abs(q)>reach:return None
            continue
        a,b=(-reach-q)/v,(reach-q)/v
        lo,hi=min(a,b),max(a,b)
        leave=min(leave,hi)
        normal=(ax*(1 if q+v*lo>0 else -1),ay*(1 if q+v*lo>0 else -1))
        if lo>enter+1e-10:enter,normals=lo,[normal]
        elif abs(lo-enter)<=1e-10:normals.append(normal)
        if enter>leave:return None
    if enter<0 or enter>1 or leave<0:return None
    return enter,tuple(normals) if normals else ((-dx/hypot(dx,dy),-dy/hypot(dx,dy)),)


def move_rectangle(tank,turn_delta,distance,walls,duration):
    heading=tank.heading_deg
    # Half-degree turn samples with a midpoint angular envelope; bounded64.
    count=ceil(abs(turn_delta)/.5)
    exhausted=count>64
    if count and not exhausted:
        step=turn_delta/count
        margin=tank.radius*abs(radians(step))/2+CONTACT_GAP
        for _ in range(count):
            candidate=(heading+step)%360
            if not rectangle_clear(tank.x,tank.y,tank.radius,candidate,walls,margin):break
            heading=candidate
    angle=radians(heading);dx,dy=distance*cos(angle),distance*sin(angle)
    x,y=tank.x,tank.y;elapsed=0.;remaining=duration;path=[]
    for _ in range(MAX_CONTACTS):
        length=hypot(dx,dy)
        if length<=CONTACT_GAP:
            path.append(Segment(elapsed,duration,x,y,x,y));break
        contacts=[c for w in walls if (c:=_sweep(x,y,tank.radius,heading,dx,dy,w)) is not None]
        if not contacts:
            path.append(Segment(elapsed,duration,x,y,x+dx,y+dy));x+=dx;y+=dy;break
        time=min(c[0] for c in contacts)
        normals=tuple(sorted({n for t,ns in contacts if abs(t-time)<=CONTACT_GAP/length for n in ns}))
        safe=max(0,time-CONTACT_GAP/length)
        nx,ny=x+dx*safe,y+dy*safe;end=elapsed+remaining*time
        path.append(Segment(elapsed,end,x,y,nx,ny));x,y=nx,ny
        dx,dy=_slide(dx*(1-time),dy*(1-time),normals)
        elapsed,remaining=end,remaining*(1-time)
    else:
        exhausted=True;path.append(Segment(elapsed,duration,x,y,x,y))
    return MoveResult(x,y,exhausted,tuple(path)),heading


def first_body_hit(bullet_path,tank_path,radius,heading,bullet_radius):
    """Exact moving circle vs translating oriented rectangle, including corners."""
    u,v=axes(heading)
    box=Rect(-radius*LENGTH_RATIO,-radius*WIDTH_RATIO,2*radius*LENGTH_RATIO,2*radius*WIDTH_RATIO)
    earliest=None
    for bullet in bullet_path:
        for body in tank_path:
            start,end=max(bullet.start,body.start),min(bullet.end,body.end)
            if end<start:continue
            bx,by=bullet.at(start);tx,ty=body.at(start)
            ex,ey=bullet.at(end);fx,fy=body.at(end)
            x,y=(bx-tx)*u[0]+(by-ty)*u[1],(bx-tx)*v[0]+(by-ty)*v[1]
            dx,dy=(ex-fx)*u[0]+(ey-fy)*u[1]-x,(ex-fx)*v[0]+(ey-fy)*v[1]-y
            if not circle_clear(x,y,bullet_radius,(box,)):hit=start
            else:
                contact=first_wall_contact(x,y,bullet_radius,dx,dy,(box,))
                if contact is None:continue
                hit=start+(end-start)*contact[0]
            earliest=hit if earliest is None else min(earliest,hit)
    return earliest
