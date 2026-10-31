"""Seeded generation must terminate and independently pass every hard condition."""
import random
import unittest
from dataclasses import replace
from unittest.mock import patch

from tank_game.map import WallEdge
from tank_game.map_records import layout_digest
from tank_game.map_validation import validate_random_map
from tests.test_map import room


class GenerationTests(unittest.TestCase):
    def test_reproducible_connected_base_is_not_global_rng_dependent(self):
        from tank_game.random_maps import generate_base
        maze = generate_base(7)
        random.seed(999)
        random.random()
        self.assertEqual(maze, generate_base(7))
        self.assertEqual((maze.columns, maze.rows, maze.tile_size, maze.wall_thickness),
                         (8, 6, 32, 2))
        self.assertEqual(len(maze.edges), 63)  # 110 edges minus 47 tree links.
        from dataclasses import asdict

        from tank_game.navigation import bfs, map_graph
        nodes, graph = map_graph({'columns': 8, 'rows': 6, 'tile_size': 32,
                                 'walls': [asdict(w) for w in maze.walls]}, 8)
        self.assertEqual(len(nodes), 48)
        self.assertTrue(all(bfs(graph, (0, 0), key) for key in nodes))

    def test_completed_maps_have_no_dead_ends_and_opposite_spawns(self):
        from tank_game.random_maps import generate_random_map
        layouts = set()
        for seed in range(10):
            record = generate_random_map(seed)
            validate_random_map(record.maze, 8, record.spawns)
            self.assertEqual(record, generate_random_map(seed))
            self.assertEqual(record.maze.spawn, record.spawns[0])
            self.assertEqual((record.spawns[0].x, record.spawns[1].x), (16, 240))
            layouts.add(record.layout_id)
        self.assertGreater(len(layouts), 1)

    def test_exclusion_and_validation_failures_are_bounded_and_explicit(self):
        from tank_game.random_maps import GenerationError, GeneratorOptions, generate_random_map
        options = GeneratorOptions(extra_openings_max=0, attempt_limit=3)
        with patch('tank_game.random_maps.generate_base', return_value=room(8, 6)):
            with self.assertRaises(GenerationError) as caught:
                generate_random_map(7, options=options, exclude_layout=layout_digest(room(8, 6)))
            self.assertEqual(len(caught.exception.rejections), 3)
        bad = replace(room(8, 6), edges=room(8, 6).edges[:-1])
        with patch('tank_game.random_maps.generate_base', return_value=bad):
            with self.assertRaises(GenerationError) as caught:
                generate_random_map(9, options=options)
            self.assertEqual(caught.exception.seed, 9)
            self.assertEqual(len(caught.exception.rejections), 3)

    def test_later_valid_candidate_preserves_attempt_and_failure_metadata(self):
        from tank_game.random_maps import generate_base, generate_random_map
        bad = replace(room(8, 6), edges=room(8, 6).edges[:-1])
        good = generate_base(8, 1)
        with patch('tank_game.random_maps.generate_base', side_effect=[bad, good]):
            record = generate_random_map(8)
        self.assertEqual(record.attempt, 1)
        self.assertEqual(len(record.rejections), 1)
        validate_random_map(record.maze, 8, record.spawns)

    def test_invalid_inputs_and_programming_errors_are_not_silent_retries(self):
        from tank_game.random_maps import GeneratorOptions, generate_random_map
        for seed in (-1, 2**32, True, 1.5):
            with self.assertRaises(ValueError):
                generate_random_map(seed)
        for values in ({'attempt_limit': 0}, {'attempt_limit': 33},
                       {'extra_openings_max': True}, {'extra_openings_max': 83}):
            with self.assertRaises(ValueError):
                GeneratorOptions(**values)
        with (patch('tank_game.random_maps.generate_base', side_effect=RuntimeError('bug')),
              self.assertRaises(RuntimeError)):
            generate_random_map(7)

    def test_repair_opens_only_internal_walls(self):
        from tank_game.random_maps import generate_base, remove_dead_ends
        base = generate_base(19)
        maze = remove_dead_ends(base, random.Random(19))
        validate_random_map(maze, 8)
        boundary = {WallEdge('horizontal', c, r) for r in (0, 6) for c in range(8)}
        boundary |= {WallEdge('vertical', c, r) for c in (0, 8) for r in range(6)}
        self.assertTrue(boundary.issubset(maze.edges))
