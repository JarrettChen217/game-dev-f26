"""Explicit H2-only profile validation; old A2 protocol rules stay unchanged."""
from dataclasses import asdict, replace
from pathlib import Path

from tank_game.learning.contracts import make_learning_contract
from tank_game.learning.ppo_protocol import ROOT, _exact, file_digest, load_protocol, read_json

BASE='data/learning/ppo-feasibility-v1/qualified-recovery-protocol.json'


def safety_learning_contract(arm):
    from tank_game.learning.safety_encoding import SafetyObservationEncoder
    identity=SafetyObservationEncoder(arm).identity()
    return asdict(replace(make_learning_contract(),profile=identity['profile'],
        observation_schema=identity['observation_schema'],observation_size=358))


def checkpoint_observation_size(metadata=None):
    if metadata is None:return 340
    try:
        contract=metadata['contracts']
        profile=contract.get('safety_profile')
        if profile is None:
            if not _exact(contract['learning'],asdict(make_learning_contract())):
                raise ValueError('incompatible original340 learning contract')
            return 340
        from tank_game.learning.safety_encoding import SafetyObservationEncoder
        arm=profile['arm']
        if (not _exact(profile,SafetyObservationEncoder(arm).identity())
                or not _exact(contract['learning'],safety_learning_contract(arm))):
            raise ValueError('incompatible safety profile/learning identity')
        return 358
    except (KeyError,TypeError,AttributeError) as error:
        raise ValueError('malformed observation/profile identity') from error


def load_safety_protocol(path:Path,manifest:dict)->dict:
    from tank_game.learning.safety_encoding import SafetyObservationEncoder
    raw=read_json(path)
    try:
        arm=raw['arm']
        profile=SafetyObservationEncoder(arm).identity()
        wanted={'schema_version':1,'kind':'hybrid-safety-h2','arm':arm,'seed':11,
            'base_protocol_path':BASE,'base_protocol_sha256':file_digest(ROOT/BASE),
            'manifest_sha256':file_digest(ROOT/'data/learning/readiness-v1/suite.json'),
            'lock_sha256':file_digest(ROOT/'uv.lock'),'profile_sha256':profile['sha256'],
            'horizon_ticks':36,'n_envs':8,'training_steps':8192,'training_seconds':600,
            'evaluation_games':4,'evaluation_seconds':180,'schedule_horizon':999424,
            'automatic_retry':False,'may_initialize_pilot':False}
        if not _exact(raw,wanted):raise ValueError('H2 candidate identity/budget drift')
        p=load_protocol(ROOT/BASE,manifest)
        p.update(kind='hybrid-safety-h2',protocol_id='public-safety-h2-'+arm,
                 freeze_stage='h2-smoke-only',seeds=[11])
        p['contracts'].update(learning=safety_learning_contract(arm),safety_profile=profile)
        p['network']['prediction_features']=arm=='features'
        p['ppo']['learning_rate'].update(schedule='linear-to-zero-over-explicit-schedule-horizon',
                                          horizon_transitions=999424)
        p['budgets'].update(per_seed_transitions=8192,per_seed_complete_updates=2,
            training_wall_seconds_per_seed=600,active_training_cutoff_seconds_per_seed=540,
            training_wall_seconds_all_seeds=600,evaluation_wall_seconds_all_seeds=180,
            evaluation_active_cutoff_seconds_all_seeds=120)
        p['evaluation'].update(split='train',condition_ids=[c['id'] for c in manifest['splits']['train'][:2]],
            checkpoint_aggregate_transitions=[0,4096,8192],checkpoint_update_indices=[0,1,2],
            games_per_checkpoint=4,mandatory_games_all_seeds=4,
            predictor_identity='public-safety-h2-'+arm)
        p['_runtime']={'path':str(Path(path).resolve()),'sha256':file_digest(path)}
        checkpoint_observation_size(p)
        return p
    except (KeyError,TypeError,AttributeError) as error:
        raise ValueError('malformed H2 protocol') from error


def safety_training_target(protocol,initial_steps):
    if protocol.get('kind')!='hybrid-safety-h2' or checkpoint_observation_size(protocol)!=358:
        raise ValueError('H2 training requires explicit safety protocol')
    if type(initial_steps) is not int or initial_steps not in (0,4096):
        raise ValueError('H2 permits only fresh0 or explicit4096 checkpoint boundary')
    return 4096 if initial_steps==0 else 8192


def make_observation_encoder(protocol):
    if 'safety_profile' not in protocol['contracts']:
        from tank_game.learning.encoding import ObservationEncoder
        return ObservationEncoder()
    from tank_game.learning.safety_encoding import SafetyObservationEncoder
    checkpoint_observation_size(protocol)
    return SafetyObservationEncoder(protocol['contracts']['safety_profile']['arm'])
