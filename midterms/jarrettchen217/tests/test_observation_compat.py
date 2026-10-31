"""Known observation migrations preserve historical evidence without rewriting it."""
import gzip
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from tank_game.evaluation import replay_trace, run_game
from tank_game.world import World

try:
    from tank_game.observation_compat import project_public_scene
except ImportError:
    project_public_scene = None

FIXTURES = Path(__file__).parent / 'fixtures/runtime_baseline'


class ObservationCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(project_public_scene, 'known-schema observation projection is missing')

    def test_downgrade_removes_only_approved_fields_and_is_detached(self):
        for duel, native, legacy in ((False,5,3),(True,6,4)):
            scene = World(duel=duel).observe('tank-1')
            self.assertEqual(scene['schema_version'], native)
            expected = deepcopy(scene)
            expected['schema_version'] = legacy
            del expected['self_status']['cooldown_remaining']
            for b in expected['bullets']:
                del b['remaining_lifetime']
            projected = project_public_scene(scene, schema_version=legacy)
            self.assertEqual(projected, expected)
            projected['rules']['tank_radius'] = 999
            self.assertEqual(scene['rules']['tank_radius'], 8)
            self.assertEqual(project_public_scene(scene, schema_version=native), scene)

    def test_cross_mode_unknown_and_upgrade_are_rejected(self):
        scene = World(duel=True).observe('tank-1')
        for version in (3,5,7,True,6.0):
            with self.subTest(version=version), self.assertRaises(ValueError):
                project_public_scene(scene, schema_version=version)
        legacy = project_public_scene(scene, schema_version=4)
        with self.assertRaises(ValueError):
            project_public_scene(legacy, schema_version=6)
        scene['schema_version'] = 99
        with self.assertRaises(ValueError):
            project_public_scene(scene, schema_version=4)

    def test_historical_trace_replays_and_new_header_declares_schema(self):
        fixture = FIXTURES / 'legacy-0.jsonl.gz'
        with gzip.open(fixture,'rt') as stream:
            header = json.loads(next(stream))
        old = replay_trace(fixture)
        self.assertEqual(old['final_scene']['schema_version'],4)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'current.gz'
            run_game(header['manifest'],header['condition'],header['assignments'],path)
            with gzip.open(path,'rt') as stream:
                rows = [json.loads(line) for line in stream]
            self.assertEqual(rows[0]['public_observation_schema_version'],6)
            replay_trace(path)
            rows[0]['public_observation_schema_version'] = 99
            with gzip.open(path,'wt') as stream:
                for row in rows:
                    stream.write(json.dumps(row)+'\n')
            with self.assertRaises(ValueError):
                replay_trace(path)

    def test_current_timer_corruption_is_not_hidden_by_legacy_projection(self):
        fixture = FIXTURES/'legacy-0.jsonl.gz'
        with gzip.open(fixture,'rt') as stream:
            header = json.loads(next(stream))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'bad.gz'
            run_game(header['manifest'],header['condition'],header['assignments'],path)
            with gzip.open(path,'rt') as stream:
                rows = [json.loads(line) for line in stream]
            scene = next(r['observations']['tank-1'] for r in rows if 'observations' in r)
            scene['self_status']['cooldown_remaining'] = .12345
            with gzip.open(path,'wt') as stream:
                for row in rows:
                    stream.write(json.dumps(row)+'\n')
            with self.assertRaisesRegex(ValueError,'observation'):
                replay_trace(path)
