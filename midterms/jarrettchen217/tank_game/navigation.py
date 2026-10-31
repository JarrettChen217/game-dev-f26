"""Public-geometry navigation; no simulation reference or hidden map state."""

from collections import deque
from math import atan2, degrees, hypot

from tank_game.controllers import keyboard_request
from tank_game.map import Rect
from tank_game.physics import circle_clear, first_wall_contact

CLEARANCE = .125  # cover public position rounding, not a physics rule


def walls_from_scene(maze):
    return tuple(Rect(**wall) for wall in maze['walls'])


def segment_clear(start, end, radius, walls):
    return (circle_clear(*start, radius, walls) and circle_clear(*end, radius, walls)
            and first_wall_contact(*start, radius, end[0]-start[0], end[1]-start[1],
                                   walls) is None)


def map_graph(maze, radius):
    """Connect adjacent floor centers only when the complete swept body fits."""
    walls = walls_from_scene(maze)
    size = maze['tile_size']
    nodes = {(col, row): ((col+.5)*size, (row+.5)*size)
             for row in range(maze['rows']) for col in range(maze['columns'])}
    nodes = {key: pos for key, pos in nodes.items()
             if circle_clear(*pos, radius+CLEARANCE, walls)}
    graph = {}
    for key, pos in sorted(nodes.items()):
        col, row = key
        neighbors = [(col-1, row), (col, row-1), (col, row+1), (col+1, row)]
        graph[key] = tuple(n for n in neighbors if n in nodes
                           and segment_clear(pos, nodes[n], radius+CLEARANCE, walls))
    return nodes, graph


def bfs(graph, start, goal):
    if start not in graph or goal not in graph:
        return ()
    parents, pending = {start: None}, deque([start])
    while pending:
        current = pending.popleft()
        if current == goal:
            path = []
            while current is not None:
                path.append(current)
                current = parents[current]
            return tuple(reversed(path))
        for neighbor in graph[current]:
            if neighbor not in parents:
                parents[neighbor] = current
                pending.append(neighbor)
    return ()


def anchor(nodes, point, radius, walls):
    """A near node is usable only if its connector also clears the walls."""
    for key in sorted(nodes, key=lambda k: (hypot(nodes[k][0]-point[0],
                                                nodes[k][1]-point[1]), k)):
        if segment_clear(point, nodes[key], radius+CLEARANCE, walls):
            return key
    return None


class Navigator:
    """BFS plus stop-and-turn steering, never directly moves a tank."""

    def __init__(self, scene):
        tank = next(t for t in scene['tanks'] if t['id'] == scene['self_id'])
        self.radius = tank['radius']
        self.walls = walls_from_scene(scene['map'])
        self.nodes, self.graph = map_graph(scene['map'], self.radius)
        self.waypoints = []
        self.arrived = False
        self.unreachable = False

    def set_goal(self, scene, goal):
        tank = next(t for t in scene['tanks'] if t['id'] == scene['self_id'])
        start = anchor(self.nodes, (tank['x'], tank['y']), self.radius, self.walls)
        route = bfs(self.graph, start, goal)
        self.waypoints = [self.nodes[key] for key in route]
        self.unreachable = not bool(route)
        self.arrived = False
        return bool(route)

    def request(self, scene):
        idle = keyboard_request(scene, set())
        if not scene['self_status']['alive']:
            return idle
        tank = next(t for t in scene['tanks'] if t['id'] == scene['self_id'])
        point = tank['x'], tank['y']
        while self.waypoints and hypot(self.waypoints[0][0]-point[0],
                                       self.waypoints[0][1]-point[1]) <= 3:
            self.waypoints.pop(0)
        if not self.waypoints:
            self.arrived = not self.unreachable
            return idle
        target = self.waypoints[0]
        dx, dy = target[0]-point[0], target[1]-point[1]
        desired = degrees(atan2(dy, dx)) % 360
        error = (desired-tank['heading_deg']+180) % 360-180
        tolerance = scene['rules']['turn_speed_deg']/10/2+.25
        if abs(error) > tolerance:
            idle['turn'] = 1 if error > 0 else -1
        else:
            idle['throttle'] = 1
        return idle
