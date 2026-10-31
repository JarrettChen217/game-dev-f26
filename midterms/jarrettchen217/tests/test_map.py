"""Uniform square cells, edge walls and circular spawn clearance."""

import math
import unittest
from dataclasses import FrozenInstanceError, replace

from tank_game.map import GameMap, Spawn, WallEdge, fixed_map


def room(columns=2, rows=2, **kwargs):
    edges = tuple([WallEdge('horizontal', x, y) for y in (0, rows)
                   for x in range(columns)]
                  + [WallEdge('vertical', x, y) for x in (0, columns)
                     for y in range(rows)])
    return GameMap(columns, rows, edges=edges, **kwargs)


class MapTests(unittest.TestCase):
    def test_fixed_map_dimensions_and_cell_center_spawn(self):
        maze = fixed_map()
        maze.validate(5)
        self.assertEqual((maze.columns, maze.rows, maze.tile_size), (8, 6, 32))
        self.assertEqual((maze.width, maze.height), (256, 192))
        self.assertEqual(maze.spawn, Spawn(16, 16, 0))
        self.assertEqual(maze, fixed_map())

    def test_all_cell_centers_are_floor(self):
        maze = fixed_map()
        for row in range(maze.rows):
            for col in range(maze.columns):
                point = Spawn((col + .5) * maze.tile_size, (row + .5) * maze.tile_size, 0)
                self.assertTrue(replace(maze, spawn=point).is_legal_spawn(5))

    def test_walls_follow_unit_grid_edges_with_uniform_thickness(self):
        maze = fixed_map()
        for edge, wall in zip(maze.edges, maze.walls, strict=True):
            if edge.orientation == 'horizontal':
                self.assertEqual((wall.x, wall.width, wall.height),
                                 (edge.column * 32, 32, 2))
            else:
                self.assertEqual((wall.y, wall.width, wall.height),
                                 (edge.row * 32, 2, 32))
            self.assertGreaterEqual(min(wall.x, wall.y), 0)
            self.assertLessEqual(wall.x + wall.width, maze.width)
            self.assertLessEqual(wall.y + wall.height, maze.height)

    def test_every_outer_boundary_is_closed(self):
        maze = fixed_map()
        for row in range(maze.rows):
            for col in (0, maze.columns):
                self.assertIn(WallEdge('vertical', col, row), maze.edges)
        for col in range(maze.columns):
            for row in (0, maze.rows):
                self.assertIn(WallEdge('horizontal', col, row), maze.edges)
        for missing in (WallEdge('horizontal', 0, 0),
                        WallEdge('horizontal', 7, 6), WallEdge('vertical', 0, 0),
                        WallEdge('vertical', 8, 5)):
            with self.assertRaises(ValueError):
                replace(maze, edges=tuple(e for e in maze.edges if e != missing)).validate(5)

    def test_map_edges_and_rectangles_are_frozen(self):
        maze = fixed_map()
        for obj, field, value in ((maze, 'tile_size', 8), (maze.spawn, 'x', 30),
                                  (maze.edges[0], 'column', 3), (maze.walls[0], 'x', 30)):
            with self.assertRaises(FrozenInstanceError):
                setattr(obj, field, value)

    def test_invalid_dimensions_and_thickness_are_rejected(self):
        maze = fixed_map()
        for name in ('columns', 'rows', 'tile_size', 'wall_thickness'):
            for value in (0, -1, True, 2.0, math.inf, math.nan, '2', None):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    replace(maze, **{name: value}).validate(5)
        with self.assertRaises(ValueError):
            replace(maze, wall_thickness=32).validate(5)

    def test_invalid_and_duplicate_edges_are_rejected(self):
        maze = fixed_map()
        invalid = [None, ('horizontal', 0, 0), WallEdge('diagonal', 0, 0),
                   WallEdge('horizontal', True, 1), WallEdge('vertical', 1, 1.0),
                   WallEdge('horizontal', -1, 1), WallEdge('horizontal', 8, 1),
                   WallEdge('horizontal', 0, 7), WallEdge('vertical', 9, 0),
                   WallEdge('vertical', 1, 6), maze.edges[0]]
        for edge in invalid:
            with self.subTest(edge=edge), self.assertRaises(ValueError):
                replace(maze, edges=maze.edges + (edge,)).validate(5)
        with self.assertRaises(ValueError):
            replace(maze, edges=list(maze.edges)).validate(5)

    def test_invalid_spawn_and_radius_are_rejected(self):
        for spawn in (None, (16, 16, 0), Spawn(True, 16, 0), Spawn(16, math.inf, 0),
                      Spawn(16, 16, math.nan), Spawn('16', 16, 0)):
            maze = replace(fixed_map(), spawn=spawn)
            self.assertFalse(maze.is_legal_spawn(5))
            with self.assertRaises(ValueError):
                maze.validate(5)
        for radius in (0, -5, True, math.inf, math.nan, '5', None):
            self.assertFalse(fixed_map().is_legal_spawn(radius))
            with self.assertRaises(ValueError):
                fixed_map().validate(radius)

    def test_wall_contact_and_outside_spawn_are_illegal(self):
        for x, y in ((7, 16), (16, 7), (0, 16), (-10, 16), (256, 16), (16, 193)):
            maze = replace(fixed_map(), spawn=Spawn(x, y, 0))
            self.assertFalse(maze.is_legal_spawn(5))
        self.assertTrue(replace(fixed_map(), spawn=Spawn(7.01, 16, 0)).is_legal_spawn(5))

    def test_internal_wall_and_endpoint_clearance(self):
        base = room()
        maze = replace(base, edges=base.edges + (WallEdge('vertical', 1, 0),))
        self.assertFalse(replace(maze, spawn=Spawn(26, 16, 0)).is_legal_spawn(5))
        self.assertTrue(replace(maze, spawn=Spawn(26, 36, 0)).is_legal_spawn(5))
        self.assertFalse(replace(maze, spawn=Spawn(27, 35, 0)).is_legal_spawn(5))

    def test_cell_paths_match_wall_edges_and_are_connected(self):
        maze = fixed_map()
        reached = {(0, 0)}
        pending = [(0, 0)]
        while pending:
            x, y = pending.pop()
            for nx, ny, edge in ((x-1, y, WallEdge('vertical', x, y)),
                                 (x+1, y, WallEdge('vertical', x+1, y)),
                                 (x, y-1, WallEdge('horizontal', x, y)),
                                 (x, y+1, WallEdge('horizontal', x, y+1))):
                if (0 <= nx < maze.columns and 0 <= ny < maze.rows
                        and edge not in maze.edges and (nx, ny) not in reached):
                    reached.add((nx, ny))
                    pending.append((nx, ny))
        self.assertEqual(len(reached), maze.columns * maze.rows)
