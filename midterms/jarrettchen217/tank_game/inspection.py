"""Public-only visual primitives and complete human-readable inspection."""

import json

from tank_game.map import GameMap, WallEdge


def format_inspection(scene: dict) -> list[str]:
    return json.dumps(scene, indent=2, sort_keys=True, ensure_ascii=True).splitlines()


def scene_geometry(scene: dict, *, original_art=False) -> tuple[tuple, ...]:
    """Project display primitives without changing authoritative scene geometry.

    Default inspection keeps the actual hit shapes. The opt-in original art uses
    the existing Tank map strokes and silhouette, not the reference hit boxes.
    """
    if original_art and 'hull_polygons' in scene:
        maze = scene['map']
        art_map = GameMap(maze['columns'], maze['rows'],
                          tuple(WallEdge(**e) for e in scene['research']['edges']),
                          tile_size=maze['tile_size'])
        return tuple(
            [('wall', w.x, w.y, w.width, w.height) for w in art_map.walls]
            + [('tank', t['x'], t['y'], t['radius'], t['heading_deg']) for t in scene['tanks']]
            + [('bullet', b['x'], b['y'], b['radius']) for b in scene['bullets']]
        )
    tanks = ([('tank_polygon', points, 11 if tid == 'tank-1' else 8)
              for tid, shapes in scene['hull_polygons'].items() for points in shapes]
             if 'hull_polygons' in scene else
             [('tank', t['x'], t['y'], t['radius'], t['heading_deg']) for t in scene['tanks']])
    return tuple(
        [('wall', w['x'], w['y'], w['width'], w['height']) for w in scene['map']['walls']]
        + tanks
        + [('bullet', b['x'], b['y'], b['radius']) for b in scene['bullets']]
    )
