"""Versioned Simple policy: public-map patrol and safe direct opportunity shots."""

from math import atan2, cos, degrees, hypot, radians, sin

from tank_game.controllers import keyboard_request
from tank_game.navigation import Navigator, segment_clear
from tank_game.physics import CONTACT_GAP, circle_clear


class SimplePatrol:
    version = 'simple-patrol-v1'

    def __init__(self):
        self.identity = None
        self.navigator = None
        self.target_index = 0
        self.targets_visited = 0
        self.previous = None
        self.stalled = 0
        self.recovery = 0

    def _initialize(self, scene, tank, identity):
        self.identity = identity
        self.navigator = Navigator(scene)
        self.targets = sorted(self.navigator.nodes)
        self.target_index = 0
        if self.targets:
            nearest = min(self.targets, key=lambda k: (hypot(
                self.navigator.nodes[k][0]-tank['x'],
                self.navigator.nodes[k][1]-tank['y']), k))
            self.target_index = self.targets.index(nearest)
        self.targets_visited = 0
        self.previous = None
        self.stalled = self.recovery = 0
        self._next_goal(scene)

    def _next_goal(self, scene):
        for _ in range(len(self.targets)):
            self.target_index = (self.target_index+1) % len(self.targets)
            if self.navigator.set_goal(scene, self.targets[self.target_index]):
                return

    def _can_shoot(self, scene, tank):
        if not scene['self_status']['can_fire']:
            return False
        radius = scene['rules']['bullet_radius']
        angle = radians(tank['heading_deg'])
        ux, uy = cos(angle), sin(angle)
        front = tank['x']+tank['radius']*ux, tank['y']+tank['radius']*uy
        muzzle = (tank['x']+(tank['radius']+radius+2*CONTACT_GAP)*ux,
                  tank['y']+(tank['radius']+radius+2*CONTACT_GAP)*uy)
        walls = self.navigator.walls
        if not segment_clear(front, muzzle, radius, walls):
            return False
        for other in scene['tanks']:
            if other['id'] == tank['id']:
                continue
            dx, dy = other['x']-tank['x'], other['y']-tank['y']
            error = (degrees(atan2(dy, dx))-tank['heading_deg']+180) % 360-180
            # A ray intersects the visible target's circle, not a generous aim cone.
            ahead, offset = dx*ux+dy*uy, abs(dx*uy-dy*ux)
            if ahead <= tank['radius']+radius or abs(error) > 4 or offset > other['radius']:
                continue
            target = tank['x']+ahead*ux, tank['y']+ahead*uy
            if (circle_clear(*muzzle, radius, walls)
                    and segment_clear(muzzle, target, radius, walls)):
                return True
        return False

    def decide(self, scene):
        idle = keyboard_request(scene, set())
        if scene['round_status'] != 'PLAYING' or not scene['self_status']['alive']:
            return idle
        tank = next(t for t in scene['tanks'] if t['id'] == scene['self_id'])
        identity = (scene['round_id'], scene['self_id'], repr(scene['map']),
                    tank['radius'], repr(scene['rules']))
        if identity != self.identity:
            self._initialize(scene, tank, identity)
        if self._can_shoot(scene, tank):
            idle['fire'] = True
            return idle
        if not self.targets:
            return idle
        point = tank['x'], tank['y']
        if self.previous is not None and hypot(point[0]-self.previous[0],
                                              point[1]-self.previous[1]) < .25:
            self.stalled += 1
        else:
            self.stalled = 0
        self.previous = point
        if self.stalled >= 16:
            self.stalled = 0
            self.recovery = 3
            self._next_goal(scene)
        if self.recovery:
            self.recovery -= 1
            idle.update(throttle=-1, turn=1)
            return idle
        req = self.navigator.request(scene)
        if self.navigator.arrived:
            self.targets_visited += 1
            self._next_goal(scene)
            req = self.navigator.request(scene)
        elif self.navigator.unreachable:
            self._next_goal(scene)
        return req
