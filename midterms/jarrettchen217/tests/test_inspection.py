"""Human inspection and visual primitives use only the public snapshot."""

import json
import subprocess
import sys
import unittest

from tank_game.inspection import format_inspection, scene_geometry
from tank_game.world import World


class InspectionTests(unittest.TestCase):
    def test_inspection_preserves_every_public_field(self):
        scene = World().observe('tank-1')
        text = '\n'.join(format_inspection(scene))
        self.assertEqual(json.loads(text), scene)
        self.assertIn('"observation_tick": 0', text)
        self.assertIn('"cooldown_remaining": 0.0', text)

    def test_geometry_uses_exact_public_walls_and_quantized_tank(self):
        scene = World().observe('tank-1')
        geometry = scene_geometry(scene)
        walls = [primitive[1:] for primitive in geometry if primitive[0] == 'wall']
        self.assertEqual(walls, [(w['x'], w['y'], w['width'], w['height'])
                                for w in scene['map']['walls']])
        tank = scene['tanks'][0]
        self.assertIn(('tank', tank['x'], tank['y'], tank['radius'], tank['heading_deg']), geometry)
        scene['tanks'][0]['x'] = 25
        self.assertIn(('tank', 25, tank['y'], tank['radius'], tank['heading_deg']),
                      scene_geometry(scene))

    def test_cli_inspection_is_headless_json(self):
        result = subprocess.run([sys.executable, '-m', 'tank_game', '--inspect'],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        from tank_game.laika_60hz.play_modes import SoloPlayWorld
        world=SoloPlayWorld();self.addCleanup(world.close)
        self.assertEqual(json.loads(result.stdout),world.observe('tank-1'))


if __name__ == '__main__':
    unittest.main()
