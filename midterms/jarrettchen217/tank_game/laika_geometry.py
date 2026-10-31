"""Public Tank queries for the Laika port; no simulation or cloned world.

Adapted from Cichlider's Killfield engine/src/{maze,ballistics}.rs (MIT).
See THIRD_PARTY_NOTICES.md. Reference neighbor order/FIFO distances and NaN
escape-field behavior are retained; collision queries use Tank's real circles.
"""
from collections import deque
from dataclasses import dataclass
from math import ceil, cos, floor, hypot, inf, nan, radians, sin, sqrt

from tank_game.hull import enabled, first_body_hit, rectangle_clear
from tank_game.navigation import map_graph, segment_clear, walls_from_scene
from tank_game.paths import Segment
from tank_game.physics import CONTACT_GAP, circle_clear, ricochet_circle

REFERENCE_HZ = 25
# Reference path/gradient tie order: four diagonals, then left/right/up/down.
PATH_ORDER = ((-1,1),(1,1),(-1,-1),(1,-1),(-1,0),(1,0),(0,-1),(0,1))
DISTANCE_ORDER = PATH_ORDER[4:] + PATH_ORDER[:4]


class PublicMaze:
    def __init__(self, scene):
        own = next(t for t in scene['tanks'] if t['id'] == scene['self_id'])
        self.rectangle = enabled(scene)
        self.size = scene['map']['tile_size']
        self.width, self.height = scene['map']['columns'], scene['map']['rows']
        self.walls = walls_from_scene(scene['map'])
        self.nodes, cardinal = map_graph(scene['map'], own['radius'])
        self.graph = {}
        for cell in self.nodes:
            x,y = cell
            neighbors = list(cardinal[cell])
            for dx,dy in PATH_ORDER[:4]:
                target, side_x, side_y = (x+dx,y+dy), (x+dx,y), (x,y+dy)
                if (target in self.nodes and side_x in cardinal[cell]
                        and side_y in cardinal[cell] and target in cardinal[side_x]
                        and target in cardinal[side_y] and segment_clear(
                            self.nodes[cell], self.nodes[target], own['radius']+.125, self.walls)):
                    neighbors.append(target)
            self.graph[cell] = tuple(neighbors)
        self._distances = {}
        self.dead_ends = self._dead_ends(cardinal)

    def cell(self, x, y):
        return floor(x/self.size), floor(y/self.size)

    def neighbors(self, cell, order=PATH_ORDER):
        x,y = cell
        edges = self.graph.get(cell, ())
        return tuple((x+dx,y+dy) for dx,dy in order if (x+dx,y+dy) in edges)

    def distances(self, start):
        if start not in self._distances:
            # Original FIFO flood is intentionally not replaced with Dijkstra.
            result, pending = {start:0.0}, deque([start])
            while pending:
                current = pending.popleft()
                for neighbor in self.neighbors(current, DISTANCE_ORDER):
                    if neighbor not in result:
                        diagonal = current[0] != neighbor[0] and current[1] != neighbor[1]
                        result[neighbor] = result[current] + (sqrt(2) if diagonal else 1)
                        pending.append(neighbor)
            self._distances[start] = result
        return self._distances[start]

    def distance(self, start, end):
        return self.distances(start).get(end, nan)

    def shortest_path(self, start, end):
        if start not in self.graph or end not in self.graph:
            return []
        distances = self.distances(start)
        current, best, path = end, distances.get(end,nan), []
        for _ in range(len(self.nodes)*4+8):
            path.append(current)
            if current == start:
                break
            nxt = current
            for neighbor in self.neighbors(current):
                if distances.get(neighbor,nan) < best:
                    nxt, best = neighbor, distances[neighbor]
            if nxt == current:
                break
            current = nxt
        return list(reversed(path))

    def gradient(self, field, start, limit=5):
        value = lambda cell: field.get(cell,nan)-self.dead_ends.get(cell,nan)
        current, best, path = start, value(start), []
        for _ in range(limit):
            nxt = current
            for neighbor in self.neighbors(current):
                if value(neighbor) > best:
                    nxt, best = neighbor, value(neighbor)
            path.append(nxt)
            if nxt == current:
                break
            current = nxt
        return path

    def _dead_ends(self, cardinal):
        result = dict.fromkeys(self.nodes,0.0)
        stack = list(self.nodes)
        while stack:
            cell = stack.pop()
            if result[cell]:
                continue
            unmarked = [n for n in cardinal[cell] if not result[n]]
            penalty = min([5]+[max(1,result[n]-1) for n in cardinal[cell] if result[n]])
            if len(unmarked) <= 1:
                result[cell] = penalty
                stack.extend(unmarked)
        return result


@dataclass(frozen=True)
class Shot:
    outcome: str
    time: float
    closest: float = inf


def muzzle(scene, tank, heading, walls):
    angle = radians(heading)
    ux,uy = cos(angle),sin(angle)
    radius = scene['rules']['bullet_radius']
    front = tank['x']+tank['radius']*ux, tank['y']+tank['radius']*uy
    distance = tank['radius']+radius+2*CONTACT_GAP
    point = tank['x']+distance*ux, tank['y']+distance*uy
    if not segment_clear(front,point,radius,walls):
        return None
    return point


def check_shot(scene, maze, tank, heading):
    """Original coarse 1/25 s samples and one-third lifetime, native radii/bounces."""
    point = muzzle(scene,tank,heading,maze.walls)
    life = scene['rules']['bullet_lifetime']/3
    if point is None:
        return Shot('nothing',life)
    x,y = point
    angle = radians(heading)
    speed = scene['rules']['bullet_speed']
    vx,vy = speed*cos(angle),speed*sin(angle)
    radius = scene['rules']['bullet_radius']
    closest = inf
    for step in range(ceil(life*REFERENCE_HZ)):
        motion = ricochet_circle(x,y,radius,vx,vy,1/REFERENCE_HZ,maze.walls)
        if motion.exhausted:
            return Shot('nothing',life,closest)
        x,y,vx,vy = motion.x,motion.y,motion.vx,motion.vy
        for target in scene['tanks']:
            if (first_body_hit(motion.path,(Segment(0,1/REFERENCE_HZ,target['x'],target['y'],target['x'],target['y']),),target['radius'],target['heading_deg'],radius) is not None
                    if enabled(scene) else hypot(target['x']-x,target['y']-y) <= target['radius']+radius):
                return Shot('suicide' if target['id']==tank['id'] else 'hit',
                            step/REFERENCE_HZ,closest)
            if target['id'] != tank['id']:
                distance = abs(target['x']-x)+abs(target['y']-y)
                if distance < min(closest,2*maze.size) and maze.distance(
                        maze.cell(target['x'],target['y']),maze.cell(x,y)) <= 2:
                    closest = distance
    return Shot('nothing',life,closest)


def first_bounce(bullet, maze, seconds):
    x,y,vx,vy = (bullet[k] for k in ('x','y','vx','vy'))
    motion = ricochet_circle(x,y,bullet['radius'],vx,vy,seconds,maze.walls)
    if not motion.contacts or len(motion.path)<2:
        return None
    first,second = motion.path[:2]
    duration = second.end-second.start
    if duration<=0:
        return None
    return (first.x1,first.y1,(second.x1-second.x0)/duration,
            (second.y1-second.y0)/duration,first.end)


def near_wall(maze, tank, heading, distance):
    angle = radians(heading)
    if maze.rectangle:
        return not rectangle_clear(tank['x']+cos(angle)*distance,tank['y']+sin(angle)*distance,
                                   tank['radius'],tank['heading_deg'],maze.walls)
    return not circle_clear(tank['x']+cos(angle)*distance,
                            tank['y']+sin(angle)*distance,tank['radius'],maze.walls)
