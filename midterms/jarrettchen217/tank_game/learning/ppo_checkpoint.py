"""Integrity-checked trusted-local SB3 bundles. Never load an untrusted model archive."""
import copy
import json
import os
import random
import shutil
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path

import numpy as np

from tank_game.learning.ppo_protocol import ROOT, file_digest, read_json
from tank_game.learning.safety_protocol import checkpoint_observation_size

SOURCE_PATHS = ('tank_game', 'scripts/train_ppo.py', 'scripts/evaluate_ppo.py', 'pyproject.toml', 'uv.lock')


def checkpoint_static_expectations(protocol):
    source_files = sorted(str(path.relative_to(ROOT)) for path in (ROOT/'tank_game').rglob('*.py'))
    source_files += list(SOURCE_PATHS[1:])
    if 'safety_profile' in protocol['contracts'] and (ROOT/'scripts/evaluate_safety_ppo.py').exists():
        source_files.append('scripts/evaluate_safety_ppo.py')
    checkpoint_observation_size(protocol)
    if protocol.get('kind')=='hybrid-safety-h3':
        source_files += ['scripts/evaluate_hybrid_ppo.py','scripts/run_hybrid_research.py','scripts/summarize_hybrid.py']
    return {'bundle_schema': 1, 'contracts': copy.deepcopy(protocol['contracts']),
            'network': copy.deepcopy(protocol['network']), 'ppo': copy.deepcopy(protocol['ppo']),
            'predictor_version': protocol['evaluation']['predictor_identity'],
            'n_envs': protocol['n_envs'], 'training_horizon': protocol['ppo']['learning_rate'].get('horizon_transitions',protocol['budgets']['per_seed_transitions']),
            'manifest_sha256': protocol['manifest_sha256'],
            'protocol_sha256': protocol['_runtime']['sha256'],
            'lock_sha256': file_digest(ROOT/'uv.lock'),
            'runtime_source_sha256': {f: file_digest(ROOT / f) for f in source_files}}


def checkpoint_expectations(protocol):
    return checkpoint_static_expectations(protocol) | {'versions': {**{name: version(name) for name in ('numpy', 'gymnasium', 'torch', 'stable-baselines3')},
                         'python_series': f'{sys.version_info.major}.{sys.version_info.minor}'}}


def _probabilities(model, observations):
    import torch
    with torch.no_grad():
        tensor = model.policy.obs_to_tensor(observations)[0]
        return model.policy.get_distribution(tensor).distribution.probs.cpu().numpy()


def _rng_state():
    import torch
    numpy_state = np.random.get_state()
    return {'python': random.getstate(),
            'numpy': [numpy_state[0], numpy_state[1].tolist(), *numpy_state[2:]],
            'torch_cpu': torch.get_rng_state().tolist()}


def _restore_rng(state):
    import torch
    def tuples(value):
        return tuple(tuples(x) for x in value) if isinstance(value, list) else value
    random.setstate(tuples(state['python']))
    n = state['numpy']
    np.random.set_state((n[0], np.asarray(n[1], dtype=np.uint32), n[2], n[3], n[4]))
    torch.set_rng_state(torch.tensor(state['torch_cpu'], dtype=torch.uint8))


def _spaces(model,metadata=None):
    if model.observation_space.shape != (checkpoint_observation_size(metadata),) or model.action_space.n != 18:
        raise ValueError('checkpoint spaces mismatch')
    if model.policy.net_arch != {'pi': [128, 128], 'vf': [128, 128]}:
        raise ValueError('checkpoint architecture mismatch')


def save_checkpoint(model, directory: Path, metadata: dict) -> Path:
    directory = Path(directory)
    if directory.exists():
        raise FileExistsError(directory)
    _spaces(model,metadata)
    width=checkpoint_observation_size(metadata)
    directory.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.' + directory.name + '-partial-', dir=directory.parent))
    try:
        details = copy.deepcopy(metadata)
        from tank_game.learning.ppo_training import _git
        details.setdefault('implementation_revision', _git('rev-parse', 'HEAD'))
        obs = details.pop('prediction_observations', None)
        if obs is None:
            obs = model._last_obs
        if obs is None:
            obs = np.zeros((1, width), dtype=np.float32)
        obs = np.asarray(obs, dtype=np.float32).reshape(-1, width)
        if not np.isfinite(obs).all():
            raise ValueError('nonfinite prediction fixture')
        probabilities = _probabilities(model, obs)
        if not np.isfinite(probabilities).all():
            raise ValueError('nonfinite saved predictions')
        np.savez(temporary / 'predictions.npz', observations=obs, probabilities=probabilities)
        rng = _rng_state()
        model.save(temporary / 'model.zip')
        (temporary / 'rng.json').write_text(json.dumps(rng, allow_nan=False) + '\n')
        details.update(model_sha256=file_digest(temporary/'model.zip'),
                       prediction_fixture_sha256=file_digest(temporary/'predictions.npz'),
                       rng_sha256=file_digest(temporary/'rng.json'),
                       sampled_steps=int(model.num_timesteps),
                       completed_updates=int(getattr(model, 'completed_updates', 0)),
                       schedule_progress=float(model._current_progress_remaining),
                       resume_semantics='fresh-episodes-completed-update')
        (temporary / 'metadata.json').write_text(json.dumps(details, indent=2, allow_nan=False) + '\n')
        os.rename(temporary, directory)
        return directory
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _validate(directory, expected):
    try:
        directory = Path(directory)
        metadata = read_json(directory/'metadata.json')
        from tank_game.learning.ppo_protocol import _exact
        for key, value in expected.items():
            if not _exact(metadata.get(key), value):
                raise ValueError('incompatible checkpoint: ' + key)
        checkpoint_observation_size(metadata)
        import re
        import subprocess
        anchor = metadata.get('implementation_revision', '')
        if (not isinstance(anchor, str) or not re.fullmatch('[0-9a-f]{40}', anchor)
                or subprocess.run(['git', 'diff', '--quiet', anchor, '--', *SOURCE_PATHS],
                                  cwd=ROOT, check=False).returncode != 0):
            raise ValueError('checkpoint implementation revision mismatch')
        for name, key in (('model.zip', 'model_sha256'), ('predictions.npz', 'prediction_fixture_sha256'),
                          ('rng.json', 'rng_sha256')):
            path = directory/name
            if path.is_symlink() or metadata[key] != file_digest(path):
                raise ValueError('corrupt checkpoint: ' + name)
        if (type(metadata['sampled_steps']) is not int or type(metadata['completed_updates']) is not int
                or metadata['completed_updates'] < 0 or metadata['sampled_steps'] % 4096
                or metadata['sampled_steps'] != metadata['completed_updates'] * 4096):
            raise ValueError('checkpoint is not a completed-update boundary')
        return metadata
    except (OSError, KeyError, TypeError) as error:
        raise ValueError('malformed checkpoint bundle') from error


def _load(directory, expected, *, cls=None):
    metadata = _validate(directory, expected)  # Before SB3 deserializes trusted-local zip.
    from stable_baselines3 import PPO

    from tank_game.learning.ppo_training import configure_cpu
    configure_cpu()
    model = (cls or PPO).load(Path(directory)/'model.zip', device='cpu')
    _spaces(model,metadata)
    with np.load(Path(directory)/'predictions.npz', allow_pickle=False) as fixture:
        actual = _probabilities(model, fixture['observations'])
        saved = fixture['probabilities']
        if (not np.isfinite(actual).all() or not np.allclose(actual, saved, atol=1e-6, rtol=1e-6)
                or not np.array_equal(actual.argmax(axis=1), saved.argmax(axis=1))):
            raise ValueError('prediction roundtrip mismatch')
    if model.num_timesteps != metadata['sampled_steps'] or model._current_progress_remaining != metadata['schedule_progress']:
        raise ValueError('checkpoint lifecycle mismatch')
    if type(metadata.get('seed')) is not int or metadata['seed'] != model.seed:
        raise ValueError('checkpoint seed mismatch')
    return model, metadata


class Predictor:
    def __init__(self, model, metadata):
        self.model = model
        self.metadata = metadata
        self.observation_size=checkpoint_observation_size(metadata)

    def __call__(self, observation):
        if (not isinstance(observation, np.ndarray) or observation.shape != (self.observation_size,)
                or observation.dtype != np.float32 or not np.isfinite(observation).all()):
            raise ValueError(f'expected finite{self.observation_size} float32 public observation')
        action = int(self.model.predict(observation, deterministic=True)[0])
        if not 0 <= action < 18:
            raise ValueError('invalid learned action')
        return action


def load_predictor(directory: Path, expected: dict):
    return Predictor(*_load(directory, expected))


def load_for_resume(directory: Path, expected: dict, *, cls=None):
    model, metadata = _load(directory, expected, cls=cls)
    model._last_obs = None
    model._last_episode_starts = None
    _restore_rng(read_json(Path(directory)/'rng.json'))
    return model, metadata


def load_policy(directory: Path, expected: dict):
    """Normal synchronous Controller policy; no desktop ProcessWorker/GUI claim."""
    from tank_game.learning.policy import EncodedPolicy
    predictor = load_predictor(directory, expected)
    if 'safety_profile' in expected['contracts']:
        from tank_game.learning.safety_encoding import SafetyEncodedPolicy
        policy=SafetyEncodedPolicy(predictor,expected['contracts']['safety_profile']['arm'])
    else:
        policy = EncodedPolicy(predictor)
    policy.version = expected['predictor_version']
    return policy
