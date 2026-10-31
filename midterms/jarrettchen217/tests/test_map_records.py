"""Map snapshots must survive algorithm changes and arbitrary edge ordering."""
import unittest
from dataclasses import replace

from tank_game.map import Spawn, fixed_map


class RecordTests(unittest.TestCase):
    def test_snapshot_roundtrip_and_detachment(self):
        from tank_game.map_records import decode_map, encode_map
        maze = fixed_map()
        raw = encode_map(maze)
        self.assertEqual(decode_map(raw), maze)
        raw['edges'][0]['column'] = 100
        self.assertEqual(maze.edges[0].column, 0)

    def test_geometry_identity_ignores_order_but_not_walls(self):
        from tank_game.map_records import layout_digest, snapshot_digest
        maze = fixed_map()
        self.assertEqual(layout_digest(maze), layout_digest(replace(
            maze, edges=tuple(reversed(maze.edges)))))
        self.assertNotEqual(layout_digest(maze), layout_digest(replace(
            maze, edges=maze.edges[:-1])))
        a = (maze.spawn, Spawn(240, 176, 180))
        b = (maze.spawn, Spawn(240, 144, 180))
        self.assertNotEqual(snapshot_digest(maze, a), snapshot_digest(maze, b))

    def test_malformed_snapshots_fail_before_use(self):
        from tank_game.map_records import decode_map, encode_map
        for change in ({'extra': 1}, {'columns': True}, {'edges': {}},
                       {'spawn': {'x': float('nan'), 'y': 16, 'heading_deg': 0}}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                decode_map(dict(encode_map(fixed_map()), **change))
