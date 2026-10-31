"""Bounded public-map pursuit toward reachable, unoccupied firing positions."""

from math import atan2, degrees, hypot

from tank_game.controllers import keyboard_request
from tank_game.navigation import Navigator, anchor, bfs, segment_clear
from tank_game.patrol import SimplePatrol


def steer(scene, tank, target):
    """Stop and turn in whole physics ticks, capped at one decision interval."""
    request = keyboard_request(scene, set())
    desired = degrees(atan2(target[1]-tank['y'], target[0]-tank['x']))
    error = (desired-tank['heading_deg']+180) % 360-180
    if abs(error) > 2:
        interval = scene['rules']['tick_rate']//10
        request.update(turn=1 if error > 0 else -1,
                       turn_ticks=interval, turn_target_deg=desired%360)
    return request


class PursuitPolicy:
    version = 'pursuit-v2'
    max_shot_distance = 160

    def __init__(self):
        self.identity = None
        self.navigator = None
        self.goal = None
        self.opponent_point = None
        self.last_plan = -100000
        self.previous = None
        self.stalled = 0
        self.fallback = SimplePatrol()

    def _reset(self, scene, identity):
        self.__init__()
        self.identity = identity
        self.navigator = Navigator(scene)

    def _firing_position(self, scene, point, other, radius):
        distance = hypot(other['x']-point[0], other['y']-point[1])
        return (radius+other['radius']+.25 < distance <= self.max_shot_distance
                and segment_clear(point, (other['x'], other['y']),
                                  scene['rules']['bullet_radius']+.125,
                                  self.navigator.walls))

    def _plan(self, scene, tank, other):
        nav = self.navigator
        start = anchor(nav.nodes, (tank['x'], tank['y']), tank['radius'], nav.walls)
        candidates = []
        for key, point in sorted(nav.nodes.items()):
            if not self._firing_position(scene, point, other, tank['radius']):
                continue
            route = bfs(nav.graph, start, key)
            if route:
                candidates.append((len(route), hypot(point[0]-other['x'],
                                                     point[1]-other['y']), key))
        goal = min(candidates)[2] if candidates else None
        if goal != self.goal or nav.unreachable or self.stalled >= 16:
            self.goal = goal
            if goal is not None:
                nav.set_goal(scene, goal)
                if (len(nav.waypoints) > 1 and segment_clear(
                        (tank['x'], tank['y']), nav.waypoints[1], tank['radius']+.125,
                        nav.walls)):
                    nav.waypoints.pop(0)
        self.opponent_point = other['x'], other['y']
        self.last_plan = scene['observation_tick']

    def decide(self, scene):
        idle = keyboard_request(scene, set())
        if scene['round_status'] != 'PLAYING' or not scene['self_status']['alive']:
            return idle
        tank = next(t for t in scene['tanks'] if t['id'] == scene['self_id'])
        identity = (scene['round_id'], scene['self_id'], repr(scene['map']),
                    tank['radius'], repr(scene['rules']))
        if identity != self.identity:
            self._reset(scene, identity)
        others = sorted((t for t in scene['tanks'] if t['id'] != tank['id']),
                        key=lambda t: t['id'])
        if not others:
            self.goal = None
            return self.fallback.decide(scene)
        other = others[0]
        point = tank['x'], tank['y']
        if self._firing_position(scene, point, other, tank['radius']):
            req = steer(scene, tank, (other['x'], other['y']))
            if SimplePatrol._can_shoot(self, scene, tank):
                req.update(turn=0, fire=True)
                req.pop('turn_ticks', None)
                req.pop('turn_target_deg', None)
            return req
        moved = (self.opponent_point is None or hypot(
            other['x']-self.opponent_point[0], other['y']-self.opponent_point[1]) >= 8)
        self.stalled = (self.stalled+1 if self.previous is not None
                        and hypot(point[0]-self.previous[0], point[1]-self.previous[1]) < .25
                        else 0)
        self.previous = point
        if moved or scene['observation_tick']-self.last_plan >= 30 or self.stalled >= 16:
            self._plan(scene, tank, other)
        if self.goal is None or self.stalled >= 16:
            return self.fallback.decide(scene)
        nav = self.navigator
        while nav.waypoints and hypot(nav.waypoints[0][0]-point[0],
                                      nav.waypoints[0][1]-point[1]) <= 3:
            nav.waypoints.pop(0)
        if not nav.waypoints:
            self.goal = None
            return self.fallback.decide(scene)
        req = steer(scene, tank, nav.waypoints[0])
        if req['turn'] == 0:
            req['throttle'] = 1
        return req
