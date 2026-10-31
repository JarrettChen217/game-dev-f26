"""Strict, stdlib-only PPO protocol loading. Configuration is not authorization."""
import hashlib
import json
import math
import re
import subprocess
from dataclasses import asdict
from pathlib import Path

from tank_game.learning.contracts import EXECUTION_PROFILE, make_learning_contract

ROOT = Path(__file__).resolve().parents[2]
TOP_KEYS = {'schema_version', 'kind', 'protocol_id', 'freeze_stage', 'created_date', 'authorship', 'research_question', 'provenance', 'qualification', 'contracts', 'manifest_path', 'manifest_sha256', 'opponent', 'backend', 'n_envs', 'subprocess_start_method', 'device', 'runtime', 'network', 'ppo', 'seeds', 'training_distribution', 'budgets', 'evaluation', 'criteria', 'safety', 'deferred'}
FROZEN = ('tank_game/config.py', 'tank_game/patrol.py', 'tank_game/actions.py',
          'tank_game/physics.py', 'tank_game/world.py', 'tank_game/learning/contracts.py',
          'tank_game/learning/encoding.py', 'tank_game/learning/actions.py')
RECOVERY_POLICY = {'version':1,'manual_pilot_resume':True,
    'checkpoint':'latest-complete-update;same-experiment-seed-mode-protocol',
    'budgets':'cumulative-actual-sampling-training-wall-and-shared-evaluation;no-refill',
    'episodes':'fresh-current-episode;restore-selector-global-RNG-optimizer-schedule',
    'completed_seeds':'preserve;reject-rerun',
    'evaluation':'reuse-completed-games;restart-only-incomplete-game;retain-attempts',
    'history':'append-attempts;resumed-is-not-uninterrupted',
    'automatic_restart':False,'unconfirmed_accounting':'preserve-and-refuse-automatic-repair'}


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def read_json(path):
    def invalid(value):
        raise ValueError(f'non-finite JSON constant: {value}')
    return json.loads(Path(path).read_text(), object_pairs_hook=_pairs, parse_constant=invalid)


def _require(value, message):
    if not value:
        raise ValueError(message)


def _integer(value, minimum=0, maximum=None):
    return type(value) is int and value >= minimum and (maximum is None or value <= maximum)


def _exact(actual, expected):
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(_exact(actual[k], v)
                                                       for k, v in expected.items())
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(_exact(a, b) for a, b in zip(actual, expected))
    return actual == expected


def load_protocol(path: Path, manifest: dict) -> dict:
    """Validate a bounded protocol without importing Gym/NumPy/Torch/SB3."""
    path = Path(path)
    p = read_json(path)
    try:
        _require(type(p) is dict and set(p) in (TOP_KEYS,TOP_KEYS|{'recovery'}), 'unexpected protocol fields')
        if 'recovery' in p:
            _require(_exact(p['recovery'], RECOVERY_POLICY), 'recovery policy drift')
        _require(_exact(p['schema_version'], 1) and p['kind'] == 'ppo-feasibility', 'protocol schema')
        _require(p['manifest_path'] == 'data/learning/readiness-v1/suite.json', 'manifest path')
        stored = ROOT / p['manifest_path']
        _require(p['manifest_sha256'] == file_digest(stored) and manifest == read_json(stored),
                 'frozen manifest mismatch')
        c = p['contracts']
        _require(_exact(c['learning'], asdict(make_learning_contract())), 'learning contract drift')
        _require(c['execution_profile'] == EXECUTION_PROFILE and c['observation_dtype'] == 'float32'
                 and _exact(c['action_count'], 18) and c['input_information'] == 'public-only'
                 and _exact(c['decision_physics_ticks'], 6) and _exact(c['round_limit_seconds'], 120)
                 and c['external_tick_limit'] is None and c['rollout_boundary_resets_episode'] is False
                 and _exact(c['observation_bounds'], [-1.0, 1.0])
                 and c['preserve_partial_terminal_decision'] is True
                 and c['natural_rule_draw'] == 'terminated'
                 and c['history_clears_on_new_round'] is True, 'environment contract drift')
        sources = p['provenance']['frozen_source_sha256']
        _require(set(sources) == set(FROZEN) and all(sources[f] == file_digest(ROOT / f)
                                                 for f in FROZEN), 'frozen source drift')
        _require(re.fullmatch('[0-9a-f]{64}', p['provenance']['baseline_lock_sha256']) is not None,
                 'baseline lock identity')  # Provenance, not the future training lock.
        _require(p['opponent']['name'] == 'simple'
                 and p['opponent']['version'] == manifest['opponents']['simple']
                 and p['opponent']['decision_timeout_seconds'] is None
                 and p['opponent']['self_play'] is False and p['opponent']['opponent_pool'] is False,
                 'frozen Simple required')
        _require(_integer(p['n_envs'], 1) and p['n_envs'] in (1, 2, 4, 8)
                 and p['backend'] in ('sequential', 'subprocess') and p['device'] == 'cpu'
                 and p['subprocess_start_method'] == 'spawn', 'bounded CPU backend required')
        _require(_exact(p['seeds'], [11, 22, 33]), 'fixed seeds required')
        net = {'policy_class': 'MlpPolicy', 'actor_hidden_sizes': [128, 128],
               'critic_hidden_sizes': [128, 128], 'activation': 'Tanh',
               'orthogonal_initialization': True, 'additional_observation_normalization': False,
               'reward_normalization': False, 'action_masking': False,
               'recurrence': False, 'prediction_features': False}
        _require(_exact(p['network'], net), 'network/public-input profile drift')
        expected = {'learning_rate': {'schedule': 'linear-to-zero-over-frozen-per-seed-horizon',
                                     'initial': 0.0003, 'final': 0.0},
                    'aggregate_rollout_transitions': 4096,
                    'n_steps_per_environment': 4096 // p['n_envs'], 'batch_size': 256,
                    'n_epochs': 4, 'gamma': 0.999, 'gae_lambda': 0.95, 'clip_range': 0.2,
                    'clip_range_vf': None, 'normalize_advantage': True, 'ent_coef': 0.01,
                    'vf_coef': 0.5, 'max_grad_norm': 0.5, 'target_kl': None, 'use_sde': False,
                    'optimizer': {'name': 'Adam', 'eps': 0.00001, 'betas': [0.9, 0.999],
                                  'weight_decay': 0.0},
                    'training_action_selection': 'sample-categorical-policy',
                    'reward': {'win': 1.0, 'loss': -1.0, 'draw': 0.0,
                               'nonterminal': 0.0, 'shaping': False},
                    'rollout_interruption': 'discard-incomplete-rollout;never-train-partial-buffer'}
        _require(_exact(p['ppo'], expected), 'PPO parameters/types drift')
        train = p['training_distribution']
        _require(train['split'] == 'train' and _exact(train['condition_count'], 64)
                 and train['condition_ids'] == [x['id'] for x in manifest['splits']['train']]
                 and train['validation_training'] is False and train['test_training'] is False,
                 'train-only map schedule required')
        schedule = {'map_sampling': 'uniform-with-replacement-at-reset-only',
            'worker_seed_derivation': 'numpy-SeedSequence-[run_seed,worker_index]-generate-one-uint32-v1',
            'reset_rng': 'numpy-default_rng-from-derived-worker-seed',
            'initial_seat_parity': 'first-reset-rng-draw-integers-2',
            'subsequent_map_rng_draw': 'one-integers-64-after-initial-parity;then-one-at-each-reset',
            'seat_order': ['tank-1', 'tank-2'],
            'seat_schedule': 'alternate-every-episode-from-seeded-initial-parity'}
        _require(all(_exact(train[k], v) for k, v in schedule.items()), 'reset schedule drift')
        _require(p['runtime']['model_location'] == 'parent-process-only'
                 and p['runtime']['render_mode'] is None
                 and p['runtime']['vec_env_class'] == ('SubprocVecEnv' if p['backend']=='subprocess' else 'DummyVecEnv'),
                 'runtime placement drift')
        for key in ('torch_num_threads', 'torch_num_interop_threads', 'OMP_NUM_THREADS',
                    'OPENBLAS_NUM_THREADS'):
            _require(_exact(p['runtime'][key], 1), 'one CPU thread required')
        b = p['budgets']
        steps = b['per_seed_transitions']
        _require(_integer(steps, 16384, 999424) and steps % 4096 == 0
                 and _exact(b['per_seed_complete_updates'], steps // 4096), 'complete-update budget')
        _require(_integer(b['training_wall_seconds_per_seed'], 61, 7200)
                 and _exact(b['shutdown_grace_seconds'], 60)
                 and b['shutdown_grace_included_in_wall_limits'] is True
                 and _exact(b['active_training_cutoff_seconds_per_seed'],
                            b['training_wall_seconds_per_seed'] - 60)
                 and _exact(b['training_wall_seconds_all_seeds'],
                            3 * b['training_wall_seconds_per_seed'])
                 and _integer(b['evaluation_wall_seconds_all_seeds'], 61, 7200)
                 and _exact(b['evaluation_active_cutoff_seconds_all_seeds'],
                            b['evaluation_wall_seconds_all_seeds'] - 60), 'wall-clock ceiling')
        _require(b['automatic_retry'] is False and b['extra_seed'] is False
                 and b['warm_start_from_smoke'] is False and b['no_step_overshoot'] is True,
                 'retry/overshoot forbidden')
        e = p['evaluation']
        indices = [0] + [math.ceil(k * (steps // 4096) / 4) for k in range(1, 5)]
        _require(e['split'] == 'validation' and e['test_split_allowed'] is False
                 and e['external_tick_limit'] is None and e['best_checkpoint_substitution'] is False
                 and e['action_selection'] == 'deterministic-argmax'
                 and e['condition_ids'] == [x['id'] for x in manifest['splits']['validation']]
                 and _exact(e['learner_ids'], ['tank-1', 'tank-2'])
                 and _exact(e['checkpoint_update_indices'], indices)
                 and _exact(e['checkpoint_aggregate_transitions'], [i * 4096 for i in indices])
                 and _exact(e['games_per_checkpoint'], 32)
                 and _exact(e['mandatory_games_all_seeds'], 480), 'evaluation schedule drift')
        _require(e['seed_selection'] is False and e['all_mandatory_games_must_complete'] is True
                 and e['baseline'] == 'own-seed-untrained-step0-model;save-before-any-update'
                 and e['primary_checkpoint'] == 'fixed-final-complete-update-endpoint', 'evaluation endpoint drift')
        trace = e['diagnostic_traces']
        _require(trace['condition_ids'] == e['condition_ids'][:2]
                 and _exact(trace['learner_ids'], e['learner_ids'])
                 and _exact(trace['maximum_all_seeds'], 12)
                 and trace['rerun_games_for_traces'] is False
                 and trace['reuse_mandatory_final_evaluation_games'] is True
                 and trace['trace_all_validation_games'] is False, 'bounded trace policy')
        criteria = p['criteria']
        _require(_exact(criteria['learning_signal'], {
            'all_three_planned_endpoints_required': True, 'all_mandatory_evaluation_required': True,
            'positive_score_delta_seeds_minimum': 2, 'median_final_minus_own_step0_score_minimum': 0.1})
            and _exact(criteria['useful_opponent_candidate'], {'learning_signal_required': True,
                'median_final_score_minimum': 0.6,
                'median_final_minus_own_step0_win_rate_strictly_greater_than': 0.0}), 'criteria drift')
        _require(_exact(p['safety']['available_memory_min_bytes'], 8 * 1024**3)
                 and _exact(p['safety']['free_disk_min_bytes'], 10 * 1024**3)
                 and _exact(p['safety']['cloud_spend_usd'], 0), 'resource profile drift')
        q = p['qualification']
        if p['freeze_stage'] == 'candidate-frozen-pending-M1-and-pipeline':
            _require(q['status'] == 'pending' and all(q[k] is None for k in (
                'training_implementation_revision', 'training_lock_sha256', 'torch_resolved_version')),
                'candidate qualification must be explicit')
        elif p['freeze_stage'] == 'pilot-frozen':
            _require(q['status'] == 'qualified'
                     and re.fullmatch('[0-9a-f]{40}', q['training_implementation_revision'] or '')
                     and re.fullmatch('[0-9a-f]{64}', q['training_lock_sha256'] or '')
                     and type(q['torch_resolved_version']) is str and q['torch_resolved_version'],
                     'pilot requires qualified identities')
        else:
            raise ValueError('unknown freeze stage')
    except (KeyError, TypeError, OverflowError, AttributeError) as error:
        raise ValueError('malformed PPO protocol') from error
    p['_runtime'] = {'path': str(path.resolve()), 'sha256': file_digest(path)}
    return p


def require_pilot_ready(protocol):
    """Technical prerequisite only; cannot substitute for Hao's execution authorization."""
    q = protocol['qualification']
    _require(protocol['freeze_stage'] == 'pilot-frozen' and q['status'] == 'qualified',
             'candidate cannot execute a pilot')
    _require(q['training_lock_sha256'] == file_digest(ROOT / 'uv.lock'), 'training lock mismatch')
    from importlib.metadata import version
    _require(q['torch_resolved_version'] == version('torch'), 'qualified Torch version mismatch')
    anchor = q['training_implementation_revision']
    result = subprocess.run(['git', 'diff', '--quiet', anchor, '--', 'tank_game', 'scripts',
                             'tests', 'pyproject.toml', 'uv.lock', '.github/workflows/ci.yml'],
                            cwd=ROOT, check=False)
    _require(result.returncode == 0, 'qualified implementation changed')
    evidence = ROOT / q['pipeline_evidence_path']
    _require(evidence.is_file() and protocol['_runtime']['sha256'] in evidence.read_text(),
             'final protocol qualification evidence missing')
