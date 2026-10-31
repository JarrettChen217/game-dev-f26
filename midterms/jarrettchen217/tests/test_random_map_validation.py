"""Reject bad final geometry, independent of generator topology."""
import unittest
from dataclasses import replace

from tank_game.map import Spawn, WallEdge
from tests.test_map import room


class ValidationTests(unittest.TestCase):
    def test_all_cells_and_opposite_spawns_are_usable(self):
        from tank_game.map_validation import validate_random_map
        result = validate_random_map(room(8, 6), 8, (Spawn(16, 16, 0), Spawn(240, 176, 180)))
        self.assertEqual(result.nodes, 48)
        self.assertEqual(result.links, 82)
        self.assertGreaterEqual(min(result.degrees), 2)
        self.assertEqual(len(result.spawn_path), 13)

    def test_connected_map_with_single_exit_cell_is_rejected(self):
        from tank_game.map_validation import MapValidationError, validate_random_map
        maze = room(8, 6)
        maze = replace(maze, edges=maze.edges + (WallEdge('vertical', 1, 0),))
        with self.assertRaises(MapValidationError) as caught:
            validate_random_map(maze, 8)
        self.assertEqual(caught.exception.code, 'dead_end')

    def test_isolated_regions_and_insufficient_body_clearance_are_rejected(self):
        from tank_game.map_validation import MapValidationError, validate_random_map
        maze = room(8, 6)
        separated = replace(maze, edges=maze.edges + tuple(
            WallEdge('vertical', 4, row) for row in range(6)))
        with self.assertRaises(MapValidationError) as caught:
            validate_random_map(separated, 8)
        self.assertEqual(caught.exception.code, 'disconnected')
        for radius in (16, 0, True, float('nan')):
            with self.assertRaises(MapValidationError):
                validate_random_map(maze, radius)

    def test_structure_and_opposite_spawn_rules_are_mandatory(self):
        from tank_game.map_validation import MapValidationError, validate_random_map
        maze = room(8, 6)
        bad_maps = [room(2, 2), replace(maze, edges=maze.edges[1:]),
                    replace(maze, edges=maze.edges + (maze.edges[0],)),
                    replace(maze, edges=maze.edges + (WallEdge('vertical', 20, 0),))]
        for bad in bad_maps:
            with self.assertRaises(MapValidationError):
                validate_random_map(bad, 8)
        for spawns in ((Spawn(16, 16, 0), Spawn(16, 16, 180)),
                       (Spawn(48, 16, 0), Spawn(240, 16, 180)),
                       (Spawn(16, 16, 90), Spawn(240, 16, 180)),
                       (Spawn(0, 16, 0), Spawn(240, 16, 180))):
            with self.assertRaises(MapValidationError):
                validate_random_map(maze, 8, spawns)
