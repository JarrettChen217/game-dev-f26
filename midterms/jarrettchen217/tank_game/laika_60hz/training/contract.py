"""Environment/time contract for reusing the existing trainer, without Torch."""
import hashlib
import json
from copy import deepcopy

from tank_game.laika_60hz.training.environment import ASSETS

TIMING = {'physics_hz': 60, 'decision_hz': 60, 'reference_hz': 25,
          'gamma': .999**(25/60), 'gae_lambda': .95**(25/60),
          'rollout_steps': 308, 'reference_rollout_seconds': 128/25,
          'schedule_decisions': 480_000_000, 'episode_steps': 1800,
          'grace_steps': 300, 'settlement_steps': 180, 'bullet_life_steps': 600,
          'idle_cap_steps': 60, 'dodge_preview_steps': 58,
          'bullet_forecast_units': 180, 'risk_forecast_steps': 72}


def environment_contract():
    manifest = json.loads((ASSETS/'manifest.json').read_text())
    return {'profile': 'source60-schema24-prep-v1', 'schema': 24,
            'features': 1028, 'bullet_masks': 10, 'actions': 18,
            'learner_seat': 0, 'internal_laika_seat': 1,
            'timing': deepcopy(TIMING), 'history_depth': 3,
            'history_cadence': 'previous native decisions,16.67ms each; formerly40ms',
            'history_frames_corrected': True, 'change_rate_units': 'changes per25Hz reference interval',
            'reward': 'reference terminal base plus once-only time-normalized style bonus',
            'task_draw_is_terminal': True, 'external_cutoff_requires_bootstrap': True,
            'resume_native_episodes': 'fresh episodes, not tick-exact recovery',
            'source_sha256': manifest['source_sha256']}


def contract_digest():
    return hashlib.sha256(json.dumps(environment_contract(), sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def validate_resume_metadata(research):
    if research.get('environment_contract_sha256') != contract_digest():
        raise ValueError('environment contract mismatch; old25Hz checkpoints require explicit migration initialization')
