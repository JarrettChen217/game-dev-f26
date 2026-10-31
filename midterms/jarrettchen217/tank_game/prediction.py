"""Receding-horizon public geometry; no World trial or private projectile data."""

from dataclasses import dataclass
from math import cos, hypot, radians, sin
from types import SimpleNamespace

from tank_game.control_math import target_turn
from tank_game.controllers import keyboard_request
from tank_game.duel import stop_pair
from tank_game.paths import Segment, first_hit, position
from tank_game.physics import move_circle, ricochet_circle
from tank_game.pursuit import PursuitPolicy

HORIZON_STEPS = 60
QUANTIZATION_MARGIN = .375


@dataclass(frozen=True)
class Forecast:
    paths: tuple
    exhausted: bool


def forecast_projectile(bullet, walls, *, dt=1/60, steps=HORIZON_STEPS):
    """Unknown lifetime: conservatively retain the observed bullet for the horizon."""
    if type(steps) is not int or not 1 <= steps <= HORIZON_STEPS:
        raise ValueError('projectile horizon must be 1 through 60 steps')
    x,y,vx,vy = (bullet[k] for k in ('x','y','vx','vy'))
    paths=[]
    exhausted=False
    for _ in range(steps):
        motion=ricochet_circle(x,y,bullet['radius'],vx,vy,dt,walls)
        paths.append(motion.path)
        exhausted |= motion.exhausted
        x,y,vx,vy=motion.x,motion.y,motion.vx,motion.vy
    return Forecast(tuple(paths),exhausted)


class HardPolicy:
    version='hard-pursuit-evasion-v3'

    def __init__(self):
        self.pursuit=PursuitPolicy()
        self.identity=None
        self.tracked_ids=set()
        self.previous_axes=None
        self.evading=False
        self.search_stats={}

    def _risk(self, scene, tank, request, forecasts):
        rules=scene['rules']
        dt=1/rules['tick_rate']
        x,y,heading=tank['x'],tank['y'],tank['heading_deg']
        first=None
        others={t['id']:(Segment(0,dt,t['x'],t['y'],t['x'],t['y']),)
                for t in scene['tanks'] if t['id'] != tank['id']}
        bodies={t['id']:SimpleNamespace(radius=t['radius']) for t in scene['tanks']}
        # Candidate axes are hypothetical continued inputs. A deliberate short
        # aiming pulse stops turning after its requested ticks instead.
        turn_steps=request.get('turn_ticks',HORIZON_STEPS)
        for step in range(HORIZON_STEPS):
            self.search_stats['tank_steps']+=1
            turn=request['turn'] if step < turn_steps else 0
            turn=target_turn(turn,heading,request.get('turn_target_deg'),
                             rules['turn_speed_deg']*dt)
            heading=(heading+turn*rules['turn_speed_deg']*dt)%360
            speed=(rules['forward_speed'] if request['throttle']>0 else
                   rules['reverse_speed'])*request['throttle']
            angle=radians(heading)
            motion=move_circle(x,y,tank['radius'],speed*dt*cos(angle),
                               speed*dt*sin(angle),self.pursuit.navigator.walls,duration=dt)
            if motion.exhausted:
                raise RuntimeError('prediction movement contact budget exhausted')
            path=stop_pair({tank['id']:motion.path,**others},bodies,dt)[tank['id']]
            x,y=position(path,dt)
            for bullet,forecast in forecasts:
                contact=first_hit(path,forecast.paths[step],tank['radius']+
                                  bullet['radius']+QUANTIZATION_MARGIN)
                if contact is not None:
                    at=step*dt+contact
                    first=at if first is None else min(first,at)
            if first is not None:
                break
        return first

    def decide(self,scene):
        idle=keyboard_request(scene,set())
        if scene['round_status']!='PLAYING' or not scene['self_status']['alive']:
            self.tracked_ids.clear()
            self.previous_axes=None
            self.evading=False
            return idle
        nominal=self.pursuit.decide(scene)
        identity=self.pursuit.identity
        if identity != self.identity:
            self.identity=identity
            self.previous_axes=None
        self.tracked_ids={b['id'] for b in scene['bullets']}
        self.search_stats={'candidates':0,'tank_steps':0,'projectile_steps':0}
        self.evading=False
        tank=next(t for t in scene['tanks'] if t['id']==scene['self_id'])
        rules=scene['rules']
        horizon=HORIZON_STEPS/rules['tick_rate']
        reach=max(rules['forward_speed'],rules['reverse_speed'])*horizon+tank['radius']
        forecasts=[]
        for bullet in scene['bullets']:
            if hypot(bullet['x']-tank['x'],bullet['y']-tank['y']) > (
                    reach+hypot(bullet['vx'],bullet['vy'])*horizon+bullet['radius']+
                    QUANTIZATION_MARGIN):
                continue
            forecast=forecast_projectile(bullet,self.pursuit.navigator.walls,
                                         dt=1/rules['tick_rate'])
            self.search_stats['projectile_steps']+=HORIZON_STEPS
            if forecast.exhausted:
                raise RuntimeError('prediction projectile contact budget exhausted')
            forecasts.append((bullet,forecast))
        if not forecasts:
            self.previous_axes=None
            return nominal
        self.search_stats['candidates']=1
        risk=self._risk(scene,tank,nominal,forecasts)
        if risk is None:
            self.previous_axes=None
            return nominal
        self.evading=True
        nominal_axes=nominal['throttle'],nominal['turn']
        choices=[(risk,nominal_axes,nominal)]
        for throttle in (-1,0,1):
            for turn in (-1,0,1):
                if (throttle,turn)==nominal_axes:
                    continue
                req=dict(idle,throttle=throttle,turn=turn)
                self.search_stats['candidates']+=1
                choices.append((self._risk(scene,tank,req,forecasts),(throttle,turn),req))
        # Keep the previous evasive axes only among equally safe alternatives.
        # Prefer little turning/more progress; all ties have a stable axis order.
        selected=max(choices,key=lambda c:(horizon+1/rules['tick_rate'] if c[0] is None else c[0],
                     c[1]==self.previous_axes,-abs(c[1][1]),c[1][0],c[1]))
        self.previous_axes=selected[1]
        response=dict(selected[2],fire=False)
        return response
