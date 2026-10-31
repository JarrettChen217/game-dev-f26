"""The Hybrid opponent is chosen by manifest and checked against the game ABI."""
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import numpy as np

from tank_game.models import contract
from tank_game.models.registry import (
    ENVIRONMENT,
    ManifestActor,
    ModelContractError,
    default_manifest,
    load_hybrid,
    resolve_manifest,
)

DEFAULT = default_manifest()


class ModelRegistryTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder)
        shutil.copy(DEFAULT, self.folder/'actor.json')
        shutil.copy(DEFAULT.with_suffix('.bin'), self.folder/'actor.bin')
        self.manifest = json.loads(DEFAULT.read_text())

    def candidate(self, change=None, weights=None):
        manifest = dict(self.manifest)
        if weights is not None:
            (self.folder/'actor.bin').write_bytes(weights)
            manifest['sha256'] = hashlib.sha256(weights).hexdigest()
        if change:
            change(manifest)
        (self.folder/'actor.json').write_text(json.dumps(manifest))
        return self.folder/'actor.json'

    def test_default_is_bundled_u19588_inference_only(self):
        actor = load_hybrid()
        self.assertEqual((actor.model_id, actor.label, actor.fallback_from), ('u19588', 'u19588', None))
        self.assertEqual(actor.manifest['sha256'], hashlib.sha256(DEFAULT.with_suffix('.bin').read_bytes()).hexdigest())
        self.assertFalse(any(name.startswith('critic.') for name in actor.tensors))
        self.assertEqual(DEFAULT.with_suffix('.bin').stat().st_size, 1046004)

    def test_selection_order_is_argument_then_environment_then_active(self):
        with patch.dict(os.environ, {ENVIRONMENT: str(self.folder/'actor.json')}):
            self.assertEqual(resolve_manifest(), (self.folder/'actor.json').resolve())
            self.assertEqual(resolve_manifest(DEFAULT), DEFAULT)
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(resolve_manifest(), DEFAULT)

    def test_swapped_model_loads_without_code_change(self):
        weights = np.frombuffer(DEFAULT.with_suffix('.bin').read_bytes(), '<f4').copy()
        weights[0] += 1e-3
        path = self.candidate(lambda m: m.update(label='u99999', update=99999), weights.tobytes())
        with patch.dict(os.environ, {ENVIRONMENT: str(path)}):
            actor = load_hybrid()
        self.assertEqual((actor.label, actor.fallback_from), ('u99999', None))
        features = np.zeros(contract.OBSERVATION, np.float32)
        self.assertIn(actor.action(features, np.zeros(contract.BULLET_SLOTS, np.uint8)), range(contract.ACTIONS))

    def test_contract_mismatches_are_explicit_errors(self):
        cases = {
            'observation': lambda m: m.update(observation=1027),
            'actions': lambda m: m.update(actions=17),
            'schema': lambda m: m.update(schema=25),
            'arch': lambda m: m.update(arch='other'),
            'environment_contract_sha256': lambda m: m.update(environment_contract_sha256='0'*64),
            'SHA256': lambda m: m.update(sha256='0'*64),
            'inference-only': lambda m: m['tensors'].update({'critic.weight': {'offset': 0, 'length': 1, 'shape': [1]}}),
        }
        for words, change in cases.items():
            with self.subTest(words), self.assertRaisesRegex(ModelContractError, words):
                ManifestActor(self.candidate(lambda m, c=change: (m.update(tensors=dict(m['tensors'])), c(m))))

    def test_malformed_manifests_are_contract_errors_that_fall_back(self):
        def swap_shape(m):
            m['tensors']['actor.weight'] = dict(m['tensors']['actor.weight'], shape=[256, 18])

        def drop_offset(m):
            m['tensors']['actor.bias'] = {k: v for k, v in m['tensors']['actor.bias'].items() if k != 'offset'}

        def overrun(m):
            last = max(m['tensors'], key=lambda n: m['tensors'][n]['offset'])
            m['tensors'][last] = dict(m['tensors'][last], length=m['tensors'][last]['length']+1)

        cases = {'shape': swap_shape, 'offset|malformed': drop_offset, 'malformed': lambda m: m.update(floats=None),
                 'layout|shape': overrun}
        for words, change in cases.items():
            path = self.candidate(lambda m, c=change: (m.update(tensors={k: dict(v) for k, v in m['tensors'].items()}), c(m)))
            with self.subTest(words):
                with self.assertRaisesRegex(ModelContractError, words):
                    ManifestActor(path)
                with redirect_stderr(StringIO()):
                    self.assertEqual(load_hybrid(path).label, 'u19588 (fallback)')
        (self.folder/'actor.json').write_text('[]')
        with self.assertRaisesRegex(ModelContractError, 'JSON object'):
            ManifestActor(self.folder/'actor.json')

    def test_contract_digest_matches_training_environment(self):
        from tank_game.laika_60hz.training.contract import contract_digest
        self.assertEqual(contract.ENVIRONMENT_CONTRACT_SHA256, contract_digest())

    def test_nonfinite_and_truncated_weights_are_rejected(self):
        weights = np.frombuffer(DEFAULT.with_suffix('.bin').read_bytes(), '<f4').copy()
        weights[5] = np.nan
        with self.assertRaisesRegex(ModelContractError, 'nonfinite'):
            ManifestActor(self.candidate(weights=weights.tobytes()))
        with self.assertRaisesRegex(ModelContractError, 'size or SHA256'):
            ManifestActor(self.candidate(weights=weights[:-1].tobytes()))
        (self.folder/'actor.bin').unlink()
        with self.assertRaisesRegex(ModelContractError, 'missing model tensors'):
            ManifestActor(self.folder/'actor.json')

    def test_rejected_model_falls_back_to_labeled_default(self):
        path = self.candidate(lambda m: m.update(observation=1027))
        log = StringIO()
        with redirect_stderr(log):
            actor = load_hybrid(path)
        self.assertEqual(actor.label, 'u19588 (fallback)')
        self.assertEqual(actor.fallback_from[0], str(path.resolve()))
        self.assertIn('rejected', log.getvalue())
        with self.assertRaises(ModelContractError):
            load_hybrid(path, fallback=False)

    def test_broken_default_is_not_hidden(self):
        broken = self.candidate(lambda m: m.update(actions=17))
        with patch('tank_game.models.registry.default_manifest', return_value=broken), \
                self.assertRaises(ModelContractError):
            load_hybrid()

    def test_play_world_labels_the_loaded_model(self):
        from tank_game.laika_60hz import mac_play
        with redirect_stderr(StringIO()):
            policy = load_hybrid(self.candidate(lambda m: m.update(observation=1027)))
        (self.folder/'manifest.json').write_text('{}')
        with patch.object(mac_play, 'PlayBridge'):
            world = mac_play.HybridPlayWorld(1000, policy=policy, assets=self.folder)
        self.assertEqual(world.model_label, 'u19588 (fallback)')
        self.assertEqual(world.presentation_seats[1], ('tank-2', 'U19588 (FALLBACK)'))

    def test_watch_hint_names_the_loaded_model(self):
        from tank_game.app import DrivingApp
        from tank_game.ui_rendering import draw_hud
        from tank_game.world import World
        from tests.test_ui_rendering import FakeWindow
        window = FakeWindow()
        app = DrivingApp(window, menu=True, clock=window.clock)
        self.addCleanup(app.close)
        scene = World().observe('tank-1')
        scene.update(presentation_mode='watch', presentation_strategy='Hybrid u99999 (fallback)')
        draw_hud(window, scene, strategy='hybrid', seed=None, keymap=app.keymap, origin=(204, 40))
        hint = ' '.join(t[2] for t in window.texts)
        self.assertIn('Watching Hybrid u99999 (fallback) vs Laika', hint)
        self.assertNotIn('u19588', hint)


if __name__ == '__main__':
    unittest.main()
