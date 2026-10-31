"""Prevent public display rounding from making a steadily moving tank stutter."""

import math
import unittest
from dataclasses import replace

from tank_game.inspection import scene_geometry
from tank_game.world import World
from tests.test_driving import drive


class PublicMotionTests(unittest.TestCase):
    def test_diagonal_public_positions_advance_each_frame_with_subpixel_accuracy(self):
        for heading in (30, 45, 60):
            world = World()
            world._tanks['tank-1'] = replace(world._tanks['tank-1'], heading_deg=heading)
            before = world.observe('tank-1')['tanks'][0]
            for _ in range(20):
                drive(world, {'w'})
                scene = world.observe('tank-1')
                tank = scene['tanks'][0]
                actual = world._tanks['tank-1']
                self.assertNotEqual((tank['x'], tank['y']), (before['x'], before['y']))
                self.assertLessEqual(abs(tank['x'] - actual.x), .0625)
                self.assertLessEqual(abs(tank['y'] - actual.y), .0625)
                self.assertIn(('tank', tank['x'], tank['y'], tank['radius'],
                               tank['heading_deg']), scene_geometry(scene))
                distance = math.hypot(tank['x'] - before['x'], tank['y'] - before['y'])
                self.assertLess(abs(distance - .75), .16)
                before = tank

    def test_precision_is_public_and_rounding_handles_half_steps_and_angle_wrap(self):
        world = World()
        world._tanks['tank-1'] = replace(world._tanks['tank-1'],
                                        x=24.0625, y=25.01, heading_deg=359.875)
        scene = world.observe('tank-1')
        self.assertEqual(scene['schema_version'], 5)
        self.assertEqual(scene['observation_precision'],
                         {'position': .125, 'heading_deg': .25, 'velocity': .125})
        tank = scene['tanks'][0]
        self.assertEqual((tank['x'], tank['y'], tank['heading_deg']), (24.125, 25, 0))


if __name__ == '__main__':
    unittest.main()
