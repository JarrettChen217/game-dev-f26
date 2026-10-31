"""Episode descriptions preserve existing fixed/random construction and retry."""
import unittest
from dataclasses import replace

from tank_game.config import GameConfig
from tank_game.map import fixed_map
from tank_game.random_maps import generate_random_map
from tank_game.world import World


class EpisodeTests(unittest.TestCase):
    def test_factory_matches_legacy_world(self):
        from tank_game.controllers import keyboard_request
        from tank_game.episodes import EpisodeSpec, create_world
        generated = generate_random_map(1)
        for maze, config, duel, spawns in (
                (fixed_map(), GameConfig(), False, None),
                (fixed_map(), replace(GameConfig(), bullet_speed=150), True, None),
                (generated.maze, GameConfig(), True, generated.spawns)):
            spec = EpisodeSpec(maze, config, duel, spawns, 1)
            factory = create_world(spec)
            legacy = World(maze, config, duel=duel, spawns=spawns, round_limit=1)
            for i in range(70):
                for world in (factory, legacy):
                    scene = world.observe('tank-1')
                    if scene['round_status'] == 'PLAYING':
                        world.submit_action('tank-1', keyboard_request(scene, {'forward'}, fire_pressed=i==0))
                    world.step()
                self.assertEqual(factory.observe('tank-1'), legacy.observe('tank-1'))
                self.assertEqual(factory.hit_events, legacy.hit_events)

    def test_retry_preserves_map_and_increments_round(self):
        from tank_game.episodes import EpisodeSpec, create_world
        world = create_world(EpisodeSpec(fixed_map(), GameConfig(), True, None, 1))
        before = world.observe('tank-1')
        world.restart(allow_active=True)
        after = world.observe('tank-1')
        self.assertEqual(after['round_id'], before['round_id'] + 1)
        self.assertEqual(after['map'], before['map'])
