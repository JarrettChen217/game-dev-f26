"""Each condition owns its map snapshot; historical schema1 still replays."""
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from tank_game.evaluation import aggregate, replay_trace, run_manifest, validate_manifest
from tests.test_evaluation import Idle


class RandomEvaluationTests(unittest.TestCase):
    def test_swapped_games_replay_without_calling_the_generator(self):
        from tank_game.random_evaluation import make_random_manifest
        manifest = make_random_manifest(range(1000, 1002), round_limit=2/60)
        manifest['strategy_versions'] = {'simple': Idle.version, 'hard': Idle.version}
        with tempfile.TemporaryDirectory() as directory:
            with patch('tank_game.evaluation.make_policy', lambda name: Idle()):
                report = run_manifest(manifest, directory)
            self.assertEqual(len(report['games']), 4)
            self.assertEqual(report['aggregate']['unique_layouts'], 2)
            for game in report['games']:
                with patch('tank_game.random_maps.generate_random_map',
                           side_effect=RuntimeError('must use snapshot')):
                    replay_trace(Path(directory)/game['trace'])
            self.assertNotEqual(report['games'][0]['assignments'], report['games'][1]['assignments'])
            self.assertEqual(report['games'][0]['map_id'], report['games'][1]['map_id'])

    def test_invalid_snapshot_and_wrong_map_identity_fail_before_games(self):
        from tank_game.random_evaluation import make_random_manifest
        manifest = make_random_manifest(range(1000, 1001))
        for field, value in (('map_id', 'wrong'), ('layout_id', 'wrong')):
            bad = deepcopy(manifest)
            bad['conditions'][0][field] = value
            with self.assertRaises(ValueError):
                validate_manifest(bad)
        bad = deepcopy(manifest)
        bad['conditions'][0]['map']['edges'] = bad['conditions'][0]['map']['edges'][:-1]
        with self.assertRaises(ValueError):
            validate_manifest(bad)

    def test_same_spawn_coordinates_on_different_maps_are_distinct_conditions(self):
        from tank_game.random_evaluation import make_random_manifest
        manifest = make_random_manifest(range(1000, 1001), round_limit=1/60)
        manifest['strategy_versions'] = {'simple': Idle.version, 'hard': Idle.version}
        with tempfile.TemporaryDirectory() as directory, patch(
                'tank_game.evaluation.make_policy', lambda name: Idle()):
            games = run_manifest(manifest, directory)['games']
        other = deepcopy(games[0])
        other['map_id'] = 'another-snapshot'
        other['layout_id'] = 'another-layout'
        result = aggregate([games[0], other])
        self.assertEqual(result['unique_initial_conditions'], 2)
        self.assertEqual(result['unique_layouts'], 2)
