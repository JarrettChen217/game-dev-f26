"""Public-only TTC18 prototype. Approximate counterfactuals, never action vetoes.

Other tanks, future fire/readiness and the duel clock are not extrapolated.
No World, owner, model, outcome or private full-precision state is consumed.
"""
import hashlib
import json
from dataclasses import asdict, dataclass
from math import cos, radians, sin
from pathlib import Path

import numpy as np

from tank_game.learning.actions import decode_action
from tank_game.learning.contracts import validate_learning_scene
from tank_game.map import Rect
from tank_game.paths import Segment, first_hit
from tank_game.physics import (
    CONTACT_GAP,
    circle_clear,
    first_wall_contact,
    move_circle,
    ricochet_circle,
)

DT=1/60
EXPIRY_TOLERANCE=10e-12


@dataclass(frozen=True)
class SafetyConfig:
    horizon_ticks: int = 36

    def __post_init__(self):
        if type(self.horizon_ticks) is not int or self.horizon_ticks!=36:
            raise ValueError('safety-v1 requires approved36-tick horizon')


def _quantized(scene):
    for tank in scene['tanks']:
        for key,scale in (('x',8),('y',8),('heading_deg',4)):
            if not float(tank[key]*scale).is_integer():
                raise ValueError('expected public quantized tank pose')
    for bullet in scene['bullets']:
        if any(not float(bullet[k]*8).is_integer() for k in ('x','y','vx','vy')):
            raise ValueError('expected public quantized bullet pose/velocity')


def _flight(x,y,vx,vy,radius,lifetime,walls,ticks):
    """Local per-tick paths; final lifetime interval may be shorter than DT."""
    paths=[]
    for step in range(ticks):
        remaining=lifetime-step*DT
        if remaining<=EXPIRY_TOLERANCE:
            break
        motion=ricochet_circle(x,y,radius,vx,vy,min(DT,remaining),walls)
        if motion.exhausted:
            raise ValueError('safety forecast projectile contact budget exhausted')
        paths.append(motion.path)
        x,y,vx,vy=motion.x,motion.y,motion.vx,motion.vy
    return paths


def _contact(flights,tank_paths,radius,lifetime):
    for step,(flight,tank) in enumerate(zip(flights,tank_paths)):
        contact=first_hit(flight,tank,radius)
        time=None if contact is None else step*DT+contact
        if time is not None and time<lifetime-EXPIRY_TOLERANCE:
            return time
    return None


def _trajectory(tank,action,walls,ticks,rules):
    x,y,heading=tank['x'],tank['y'],tank['heading_deg']
    paths=[]
    first_pose=None
    speed=(rules['forward_speed'] if action.throttle>0 else rules['reverse_speed'])*action.throttle
    for _ in range(ticks):
        heading=(heading+action.turn*rules['turn_speed_deg']*DT)%360
        angle=radians(heading)
        motion=move_circle(x,y,tank['radius'],speed*DT*cos(angle),speed*DT*sin(angle),
                           walls,duration=DT)
        if motion.exhausted:
            raise ValueError('safety forecast movement contact budget exhausted')
        x,y=motion.x,motion.y
        paths.append(motion.path)
        if first_pose is None:
            first_pose=(x,y,heading)
    return paths,first_pose


def _newborn(tank,pose,walls,rules):
    x,y,heading=pose
    angle=radians(heading);ux,uy=cos(angle),sin(angle)
    radius=rules['bullet_radius'];distance=tank['radius']+radius+2*CONTACT_GAP
    front_x,front_y=x+tank['radius']*ux,y+tank['radius']*uy
    bx,by=x+distance*ux,y+distance*uy
    if (not circle_clear(front_x,front_y,radius,walls)
            or not circle_clear(bx,by,radius,walls)
            or first_wall_contact(front_x,front_y,radius,bx-front_x,by-front_y,walls) is not None):
        return None
    return bx,by,rules['bullet_speed']*ux,rules['bullet_speed']*uy


class SafetyForecast:
    def __init__(self,config=None):
        if config is None:
            config=SafetyConfig()
        if type(config) is not SafetyConfig:
            raise ValueError('expected versioned SafetyConfig')
        self.config=config

    def identity(self):
        root=Path(__file__).resolve().parents[2]
        sources=('tank_game/learning/safety.py','tank_game/learning/contracts.py',
                 'tank_game/learning/actions.py','tank_game/physics.py','tank_game/paths.py')
        identity={'provider':'public-ttc18-v1','config':asdict(self.config),
                  'output':'float32[18]:first-intersection-time/horizon,capped1',
                  'assumptions':'held-movement;ready-now-one-birth-shot;unattributed-shells;'
                                'ignore-other-tanks-and-future-shots;half-open-expiry;quantized-public',
                  'source_sha256':{p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in sources}}
        identity['sha256']=hashlib.sha256(json.dumps(identity,sort_keys=True,
                                        separators=(',',':')).encode()).hexdigest()
        return identity

    def features(self,scene:dict)->np.ndarray:
        validate_learning_scene(scene)
        _quantized(scene)
        result=np.ones(18,dtype=np.float32)
        if scene['round_status']!='PLAYING' or not scene['self_status']['alive']:
            return result
        if not scene['bullets'] and not scene['self_status']['can_fire']:
            return result
        own=next(t for t in scene['tanks'] if t['id']==scene['self_id'])
        walls=tuple(Rect(**w) for w in scene['map']['walls'])
        rules=scene['rules'];ticks=self.config.horizon_ticks;horizon=ticks*DT
        flights=[(b,_flight(b['x'],b['y'],b['vx'],b['vy'],b['radius'],
                           b['remaining_lifetime'],walls,ticks)) for b in scene['bullets']]
        # Fire/nonfire share each of nine candidate movement paths.
        for index in range(0,18,2):
            action=decode_action(index)
            paths,pose=_trajectory(own,action,walls,ticks,rules)
            contacts=[_contact(flight,paths,own['radius']+b['radius'],b['remaining_lifetime'])
                      for b,flight in flights]
            earliest=min((time for time in contacts if time is not None),default=horizon)
            result[index:index+2]=min(earliest/horizon,1.)
            # World ends thetick before firing if an existing shell hits, including at DT.
            if scene['self_status']['can_fire'] and earliest>DT:
                newborn=_newborn(own,pose,walls,rules)
                if newborn is not None:
                    flight=_flight(*newborn,rules['bullet_radius'],rules['bullet_lifetime'],walls,ticks)
                    x,y,_=pose
                    # Birth motion tests the updated stationary pose, not the earlier tank sweep.
                    birth_paths=[(Segment(0,DT,x,y,x,y),),*paths[1:]]
                    contact=_contact(flight,birth_paths,own['radius']+rules['bullet_radius'],
                                     rules['bullet_lifetime'])
                    if contact is not None:
                        result[index+1]=min(result[index+1],contact/horizon)
        if result.shape!=(18,) or not np.isfinite(result).all() or ((result<0)|(result>1)).any():
            raise ValueError('invalid safety feature output')
        return result
