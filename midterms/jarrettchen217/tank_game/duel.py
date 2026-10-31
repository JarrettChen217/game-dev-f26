"""Host duel setup and conservative simultaneous body-contact resolution."""

from dataclasses import asdict, replace
from math import hypot

from tank_game.map import Spawn
from tank_game.navigation import anchor, bfs, map_graph, walls_from_scene
from tank_game.paths import Segment, first_hit, position
from tank_game.physics import CONTACT_GAP


def legal_spawns(maze, radius, spawns):
    public = {'walls': [asdict(w) for w in maze.walls], 'columns': maze.columns,
              'rows': maze.rows, 'tile_size': maze.tile_size}
    nodes, graph = map_graph(public, radius)
    walls = walls_from_scene(public)
    first = maze.spawn
    start = anchor(nodes, (first.x, first.y), radius, walls)
    if spawns is None:
        choices = [key for key in nodes if bfs(graph, start, key)
                   and hypot(nodes[key][0]-first.x, nodes[key][1]-first.y) > 2*radius]
        if not choices:
            raise ValueError('Map has no reachable second spawn')
        key = max(choices, key=lambda k: (len(bfs(graph, start, k)), k))
        spawns = (first, Spawn(*nodes[key], 180))
    if type(spawns) is not tuple or len(spawns) != 2:
        raise ValueError('Duel needs exactly two spawns')
    for spawn in spawns:
        if type(spawn) is not Spawn:
            raise ValueError('Invalid duel spawn')
        replace(maze, spawn=spawn).validate(radius)
    a, b = spawns
    if hypot(a.x-b.x, a.y-b.y) < 2*radius:
        raise ValueError('Tank spawns overlap')
    begin, end = (anchor(nodes, (s.x, s.y), radius, walls) for s in spawns)
    if not bfs(graph, begin, end):
        raise ValueError('Tank spawns are not connected with body clearance')
    return spawns


def truncate(path, time, duration):
    """Keep timed wall-safe legs and add a stationary remainder."""
    result = []
    for leg in path:
        if leg.start >= time:
            break
        end = min(leg.end, time)
        x, y = leg.at(end)
        result.append(Segment(leg.start, end, leg.x0, leg.y0, x, y))
        if end == time:
            break
    x, y = position(path, time)
    result.append(Segment(time, duration, x, y, x, y))
    return tuple(result)


def stop_pair(paths, tanks, duration):
    """Both bodies stop at entering contact; separating/tangent contact is free."""
    ids = sorted(paths)
    if len(ids) != 2:
        return paths
    first, second = ids
    radius = tanks[first].radius + tanks[second].radius
    contacts = []
    for a in paths[first]:
        for b in paths[second]:
            start, end = max(a.start, b.start), min(a.end, b.end)
            if end <= start:
                continue
            ax, ay = a.at(start)
            bx, by = b.at(start)
            ex, ey = a.at(end)
            fx, fy = b.at(end)
            px, py = ax-bx, ay-by
            dx, dy = ex-fx-px, ey-fy-py
            if hypot(px, py) <= radius + CONTACT_GAP and px*dx+py*dy >= -1e-10:
                continue
            hit = first_hit((a,), (b,), radius)
            if hit is not None:
                speed = hypot(dx, dy)/(end-start)
                contacts.append(max(start, hit-2*CONTACT_GAP/max(speed, CONTACT_GAP)))
    if not contacts:
        return paths
    time = min(contacts)
    return {key: truncate(path, time, duration) for key, path in paths.items()}
