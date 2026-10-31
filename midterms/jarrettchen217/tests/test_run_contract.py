"""Run compatibility tracks resolved game setup rather than host metadata."""
import unittest
from dataclasses import replace

from tank_game.config import GameConfig
from tank_game.duel import legal_spawns
from tank_game.map import fixed_map


class ContractTests(unittest.TestCase):
    def test_contract_tracks_rules_not_host_metadata(self):
        from tank_game.contracts import make_run_contract
        from tank_game.episodes import EpisodeSpec, create_world
        spec = EpisodeSpec(fixed_map(), GameConfig(), True, None, 120)
        contract = make_run_contract(spec)
        resolved = replace(spec, spawns=legal_spawns(spec.game_map, spec.config.tank_radius, None))
        self.assertEqual(contract, make_run_contract(resolved))
        changed = replace(spec, config=replace(spec.config, bullet_speed=150))
        self.assertNotEqual(contract.episode_digest, make_run_contract(changed).episode_digest)
        spawns = list(resolved.spawns)
        spawns[0] = replace(spawns[0], heading_deg=90)
        self.assertNotEqual(contract.episode_digest, make_run_contract(replace(spec, spawns=tuple(spawns))).episode_digest)
        for hz in (7, 0, True, 10.0):
            with self.assertRaises(ValueError): make_run_contract(spec, decision_hz=hz)
        self.assertEqual(contract.physics_hz, 60)
        self.assertEqual(contract.decision_hz, 10)
        scene = create_world(spec).observe('tank-1')
        self.assertEqual(contract.public_observation_schema_version, scene['schema_version'])
        self.assertNotIn('episode_digest', scene)
        self.assertNotIn('seed', scene)
