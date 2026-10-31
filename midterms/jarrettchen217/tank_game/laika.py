"""Native public-scene Laika, adapted from Cichlider's laika.rs (MIT).

The reference's three phases and LIFO semantics are preserved. This is a port
of the scripted opponent, not MPC/Hard. See docs/evidence/native-laika.md for
geometry, observation and timing differences; THIRD_PARTY_NOTICES.md for MIT.
"""
from dataclasses import dataclass
from math import atan2, ceil, cos, degrees, floor, hypot, inf, nan, radians, sin
from random import Random

from tank_game.controllers import keyboard_request
from tank_game.hull import enabled, lateral_extent
from tank_game.laika_geometry import (
    REFERENCE_HZ,
    PublicMaze,
    check_shot,
    first_bounce,
    near_wall,
)
from tank_game.navigation import CLEARANCE, segment_clear
from tank_game.physics import circle_clear


def reference_angle(heading):
    angle = (heading+90)%360
    return angle-360 if angle>180 else angle


def js_round(value):
    return floor(value+.5)


def turn_toward(target, current):
    if target == current:
        return 0
    return (1 if target>current else -1)*(-1 if abs(target-current)>180 else 1)


@dataclass
class Goal:
    kind: str = 'idle'
    priority: float = 0
    period: float = 15/REFERENCE_HZ
    continuous: bool = True
    data: object = None


@dataclass
class StackAction:
    kind: str
    data: object = None
    remaining: float = 0
    tolerance: float | None = None
    escape_line: tuple | None = None


class LaikaPolicy:
    version = 'laika-native-v3'
    decision_hz = 20  # host preference, not a reference-algorithm clock

    def __init__(self, *, decision_hz=20):
        if type(decision_hz) is not int or decision_hz<=0:
            raise ValueError('positive integer decision_hz required')
        self.decision_hz = decision_hz
        self.identity = None
        self.goal = Goal()
        self.actions = []
        self.aggression = .5
        self.stuck_time = 0
        self.last_tick = None
        self.previous = None
        self.trigger_held = False
        self.rng = Random(0)
        self.stats = {}

    def _reset(self, scene, identity):
        self.__init__(decision_hz=self.decision_hz)
        self.identity = identity
        self.maze = PublicMaze(scene)
        # A policy-local, public-data seed: never consume authoritative World RNG.
        self.rng.seed(repr(identity))

    def _offer(self, candidate):
        if self.goal.priority < candidate.priority:
            self.goal = candidate

    def _shot(self, scene, tank, angle):
        self.stats['shot_queries'] += 1
        return check_shot(scene,self.maze,tank,(angle-90)%360)

    def _obstructed(self, scene, tank):
        """Public own-motion inference, not the engine's private contact flag."""
        public_contact = scene['self_status'].get('wall_blocked',scene['self_status'].get('wall_contact'))
        if type(public_contact) is bool:
            return public_contact
        if self.previous is None:
            return False
        previous, throttle = self.previous
        if not throttle:
            return False
        moved = hypot(tank['x']-previous['x'],tank['y']-previous['y'])
        elapsed = (scene['observation_tick']-self.last_tick)/scene['rules']['tick_rate']
        speed = scene['rules']['forward_speed' if throttle>0 else 'reverse_speed']
        return moved < min(.25,speed*elapsed/2)

    def _dodge(self, scene, tank):
        size = self.maze.size
        own_cell = self.maze.cell(tank['x'],tank['y'])
        best, found = 4*size, None
        max_time = 75/REFERENCE_HZ
        max_cells = max_time*scene['rules']['bullet_speed']/size
        for bullet in scene['bullets']:
            self.stats['bullets_scanned'] += 1
            if not self.maze.distance(own_cell,self.maze.cell(bullet['x'],bullet['y']))<=max_cells:
                continue
            remaining = bullet['remaining_lifetime']
            rays = [(bullet['x'],bullet['y'],bullet['vx'],bullet['vy'],0)]
            if best > size/4:
                bounce = first_bounce(bullet,self.maze,min(12/REFERENCE_HZ,remaining))
                if bounce is not None:
                    rays.append(bounce)
            for x,y,vx,vy,offset in rays:
                speed2 = vx*vx+vy*vy
                if not speed2:
                    continue
                t = ((tank['x']-x)*vx+(tank['y']-y)*vy)/speed2
                if not ((-1/REFERENCE_HZ if not offset else 0)<t<min(max_time-offset,remaining-offset)):
                    continue
                closest = x+t*vx,y+t*vy
                distance = hypot(tank['x']-closest[0],tank['y']-closest[1])
                if distance >= best:
                    continue
                # Keep the reference unobstructed closest-approach tests.
                if (segment_clear((x,y),closest,bullet['radius'],self.maze.walls)
                        and segment_clear(closest,(tank['x'],tank['y']),0,self.maze.walls)):
                    best = distance
                    found = Goal('dodge',1,10/REFERENCE_HZ,False,
                                 (bullet,closest,distance,t+offset,(vx,vy)))
        return found

    def _choose_goal(self, scene, tank, dt):
        if self.goal.period > 1e-10:
            self.goal.period = max(0,self.goal.period-dt)
            return self.goal.continuous
        self.stats['goal_updates'] += 1
        self.goal.priority *= .9000000000000002
        old_goal = self.goal
        dodge = self._dodge(scene,tank)
        if dodge is not None:
            self._offer(dodge)
        own_cell = self.maze.cell(tank['x'],tank['y'])
        others = [t for t in scene['tanks'] if t['id']!=tank['id']]
        active = scene['self_status']['active_bullets']
        capacity = scene['rules']['max_bullets']
        if active < capacity:
            for target in others:
                path = self.maze.shortest_path(own_cell,self.maze.cell(target['x'],target['y']))
                length = len(path)
                if length and length < 7:
                    priority = 1 if length<=2 else ((7-length)/7)*self.aggression
                    self._offer(Goal('shoot',priority,10/REFERENCE_HZ,False,target['id']))
        if others and active == capacity:
            # Reference undersized (w-1)*(h-1) field; absent border stays NaN.
            # Opponent ammo is UNKNOWN: conservatively include each alive threat.
            field = {(x,y):sum(self.maze.distance(self.maze.cell(t['x'],t['y']),(x,y))
                              for t in others)
                     for x in range(self.maze.width-1) for y in range(self.maze.height-1)}
            here = field.get(own_cell,nan)
            if here < 10:
                self._offer(Goal('flee',((10-here)/10)*.7000000000000001,
                                 10/REFERENCE_HZ,False,field))
        self.stuck_time = min(1,self.stuck_time+1) if self._obstructed(scene,tank) else 0
        self._offer(Goal('back',self.stuck_time/.9,5/REFERENCE_HZ,False))
        if others:
            target = others[self.rng.randrange(len(others))]
            self._offer(Goal('drive',.1,10/REFERENCE_HZ,False,
                             self.maze.cell(target['x'],target['y'])))
        if self.goal is not old_goal:
            if self.goal.kind == 'shoot':
                self.aggression = max(0,self.aggression-.2)
            # A native asynchronous input may arrive one/two physics ticks late.
            # Recentring every source goal period can then erase all progress
            # before crossing half a cell. Refresh priority/timers, but finish
            # the existing route when the pursuit destination is unchanged.
            return not (self.goal.kind == old_goal.kind == 'drive'
                        and self.goal.data == old_goal.data and self.actions)
        self.aggression = min(.5,self.aggression+.5/50)
        return self.goal.continuous

    def _push_path(self, path):
        for cell in reversed(path[1:]):
            self.actions.append(StackAction('field',cell))
        if path:
            point = self.maze.nodes[path[0]]
            self.actions.append(StackAction('position',(*point,len(path)<=2)))

    def _retaliate(self, scene, tank):
        if self.aggression < .25 or scene['self_status']['active_bullets']>=scene['rules']['max_bullets']:
            return
        shot = self._shot(scene,tank,reference_angle(tank['heading_deg']))
        if shot.outcome=='hit' or (shot.outcome=='nothing' and shot.closest<self.maze.size):
            self.actions.append(StackAction('fire',remaining=1/REFERENCE_HZ))
            self.aggression = max(0,self.aggression-.2)

    def _build_actions(self, scene, tank):
        continuing_escape=any(a.kind=='position' and a.tolerance is not None for a in self.actions)
        self.actions.clear()
        size = self.maze.size
        own_cell = self.maze.cell(tank['x'],tank['y'])
        current = reference_angle(tank['heading_deg'])
        turn_step = scene['rules']['turn_speed_deg']/REFERENCE_HZ
        kind = self.goal.kind
        if kind=='shoot':
            target = next((t for t in scene['tanks'] if t['id']==self.goal.data),None)
            if target is None:
                return
            dx,dy = target['x']-tank['x'],target['y']-tank['y']
            found = segment_clear((tank['x'],tank['y']),(target['x'],target['y']),0,self.maze.walls)
            angle, best_angle, best_time, closest = current,current,inf,inf
            if found:
                best_angle = reference_angle(degrees(atan2(dy,dx)))
                closest = 0
            else:
                for k in range(1,4):
                    shot = self._shot(scene,tank,angle)
                    if shot.outcome=='hit':
                        found = True
                        if shot.time < best_time:
                            best_time,closest,best_angle = shot.time,0,angle
                    elif shot.outcome=='nothing' and not found and shot.closest<closest:
                        closest,best_angle = shot.closest,angle
                    angle += turn_step*k*k*(1 if self.rng.random()<.5 else -1)
                    if angle < -180:
                        angle += 360
                    if angle > 180:
                        angle -= 360
            if found or closest<2*size:
                self.actions.append(StackAction('fire',remaining=5/REFERENCE_HZ))
                self.actions.append(StackAction('turn',best_angle))
            elif best_angle != current:
                self.actions.append(StackAction('turn',best_angle))
            else:
                angle = current+180
                self.actions.append(StackAction('turn',angle-360 if angle>180 else angle))
        elif kind=='drive':
            self._push_path(self.maze.shortest_path(own_cell,self.goal.data))
        elif kind=='flee':
            self._push_path(self.maze.gradient(self.goal.data,own_cell))
        elif kind=='back':
            x,y = (v*size+size/2 for v in own_cell)
            self.actions.append(StackAction('position',(x,y,False)))
            front = near_wall(self.maze,tank,tank['heading_deg'],tank['radius']*.1)
            rear = near_wall(self.maze,tank,tank['heading_deg']+180,tank['radius']*.1)
            left = near_wall(self.maze,tank,tank['heading_deg']-90,tank['radius']*.3)
            action = ('backup_turn' if rear else 'backup') if front else ('forward' if rear else 'backup')
            self.actions.append(StackAction(action,-1 if left else 1,
                                            (5 if front and rear else 3)/REFERENCE_HZ))
        elif kind=='dodge':
            bullet,closest,distance,time,direction = self.goal.data
            field = self.maze.distances(self.maze.cell(bullet['x'],bullet['y']))
            path = self.maze.gradient(field,own_cell)
            close_call = time<25/REFERENCE_HZ and distance<4*size/5
            if close_call or len(path)<=1:
                angle = reference_angle(degrees(atan2(direction[1],direction[0])))
                if 90<abs(angle-current)<270:
                    angle += 180
                    if angle>180:
                        angle -= 360
                self.actions.append(StackAction('turn',js_round(angle/turn_step)*turn_step))
                clearance = (lateral_extent(tank['radius'],(angle-90)%360,*direction)
                             if enabled(scene) and not continuing_escape else tank['radius'])+bullet['radius']+.375
                if distance<max(size/4,clearance):
                    length = hypot(*direction)
                    if length:
                        px,py = -direction[1]/length,direction[0]/length
                        safe_clearance=tank['radius']+bullet['radius']+.375
                        distance_from_line=max(size/2,safe_clearance+1)
                        p1 = closest[0]+px*distance_from_line,closest[1]+py*distance_from_line
                        p2 = closest[0]-px*distance_from_line,closest[1]-py*distance_from_line
                        d1 = hypot(tank['x']-p1[0],tank['y']-p1[1])
                        d2 = hypot(tank['x']-p2[0],tank['y']-p2[1])
                        target = p1 if d1<d2 else p2
                        self.actions.append(StackAction('position',(*target,True),tolerance=.125,
                                                        escape_line=(*closest,*direction,safe_clearance)))
            else:
                self._push_path(path)
            self._retaliate(scene,tank)
        else:
            self.actions.append(StackAction('idle'))

    def _execute(self, scene, tank, dt):
        request = keyboard_request(scene,set())
        current = reference_angle(tank['heading_deg'])
        step = scene['rules']['turn_speed_deg']/REFERENCE_HZ
        size = self.maze.size
        if self.actions:
            action = self.actions.pop()
            keep = False
            if action.kind=='field':
                x,y = self.maze.nodes[action.data]
                keep = abs(tank['x']-x)>size/3 or abs(tank['y']-y)>size/3
            elif action.kind=='position':
                x,y,_ = action.data
                tolerance = size/4 if action.tolerance is None else action.tolerance
                keep = abs(tank['x']-x)>tolerance or abs(tank['y']-y)>tolerance
                if action.escape_line is not None:
                    cx,cy,vx,vy,clearance=action.escape_line
                    lateral=abs((tank['x']-cx)*vy-(tank['y']-cy)*vx)/hypot(vx,vy)
                    keep=lateral<clearance
            elif action.kind=='turn':
                keep = abs(current-action.data)>=step  # original raw-angle comparison
            elif action.kind=='idle':
                keep = True
            else:
                keep = action.remaining>1e-10
                factor = 2 if action.kind=='forward_turn' else 1  # source fallthrough quirk
                action.remaining = max(0,action.remaining-dt*factor)
            if keep:
                self.actions.append(action)
        if not self.actions:
            self.goal.period = 0
            return request
        action = self.actions[-1]
        kind = action.kind
        if kind=='field':
            fx,fy = self.maze.cell(tank['x'],tank['y'])
            x,y = action.data
            target = -90 if fx>x else 90 if fx<x else 0 if fy>y else 180 if fy<y else current
            request.update(turn=turn_toward(target,current),
                           throttle=int(not 90<abs(target-current)<270))
        elif kind=='turn':
            request['turn'] = turn_toward(action.data,current)
            request['turn_target_deg'] = (action.data-90)%360
        elif kind=='fire':
            request['fire'] = True
        elif kind=='position':
            x,y,can_reverse = action.data
            dx,dy = x-tank['x'],y-tank['y']
            target = reference_angle(degrees(atan2(dy,dx))) if dx or dy else current
            target = step*js_round(target/step)
            reverse = can_reverse and 90<abs(target-current)<270
            if reverse:
                target += 180
                if target>180:
                    target -= 360
            delta = abs(target-current)
            turn = turn_toward(target,current) if step<delta<360-step else 0
            request.update(turn=turn,throttle=0 if 45<delta<315 else -1 if reverse else 1)
        elif kind in ('forward','backup','forward_turn','backup_turn'):
            request.update(throttle=1 if kind.startswith('forward') else -1,
                           turn=action.data if kind.endswith('_turn') else 0)
        if (enabled(scene) and kind in ('field','position') and action.escape_line is None
                and request['throttle'] and request['turn']
                and circle_clear(tank['x'],tank['y'],tank['radius']+CLEARANCE,self.maze.walls)):
            # Native rectangles can drive closer to a wall than they can turn.
            # Keep the navigation graph's circular turning room over the next
            # decision interval. Pause translation only; retain source steering,
            # route/stack, goal arbitration and explicit escape/backup actions.
            # If already outside this envelope, leave source recovery free to
            # translate back out rather than freezing it with a failed start test.
            hz = scene['rules']['tick_rate']
            speed = scene['rules']['forward_speed' if request['throttle']>0 else 'reverse_speed']
            x,y,heading = tank['x'],tank['y'],tank['heading_deg']
            for _ in range(ceil(hz/self.decision_hz)):
                heading += request['turn']*scene['rules']['turn_speed_deg']/hz
                angle = radians(heading)
                distance = request['throttle']*speed/hz
                point = x+distance*cos(angle),y+distance*sin(angle)
                if not segment_clear((x,y),point,tank['radius']+CLEARANCE,self.maze.walls):
                    request['throttle'] = 0
                    break
                x,y = point
        return request

    def decide(self, scene):
        if scene['round_status']!='PLAYING' or not scene['self_status']['alive']:
            self.actions.clear()
            self.identity = None
            return keyboard_request(scene,set())
        tank = next(t for t in scene['tanks'] if t['id']==scene['self_id'])
        identity = (scene['round_id'],scene['self_id'],repr(scene['map']),repr(scene['rules']),tank['radius'],
                    repr(scene.get('collision_profile')))
        if identity != self.identity:
            self._reset(scene,identity)
        tick = scene['observation_tick']
        if self.last_tick is not None and tick<=self.last_tick:
            # A repeated observation must not consume timers or repeat a fire edge.
            return keyboard_request(scene,set())
        dt = 0 if self.last_tick is None else (tick-self.last_tick)/scene['rules']['tick_rate']
        self.stats = {'goal_updates':0,'bullets_scanned':0,'shot_queries':0}
        if self._choose_goal(scene,tank,dt):
            self._build_actions(scene,tank)
        request = self._execute(scene,tank,dt)
        wants_fire = request['fire']
        request['fire'] = bool(wants_fire and not self.trigger_held
                               and scene['self_status']['can_fire'])
        if not wants_fire:
            self.trigger_held = False
        elif request['fire']:
            self.trigger_held = True
        self.previous = dict(tank),request['throttle']
        self.last_tick = tick
        return request
