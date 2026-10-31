"""Strict bounded H3 adapter. Old A2/H2 protocols and checks stay unchanged."""
from pathlib import Path

from tank_game.learning.ppo_protocol import ROOT, _exact, file_digest, load_protocol, read_json
from tank_game.learning.safety_protocol import (
    BASE,
    checkpoint_observation_size,
    safety_learning_contract,
)

MANIFEST='data/learning/readiness-v1/suite.json'
ORDER=(('control',11),('features',11),('features',22),('control',22),('control',33),('features',33))
STEPS=249856


def candidate(arm):
    from tank_game.learning.safety_encoding import SafetyObservationEncoder
    profile=SafetyObservationEncoder(arm).identity()
    return {'schema_version':1,'kind':'hybrid-safety-h3','arm':arm,'seeds':[11,22,33],
        'base_protocol_path':BASE,'base_protocol_sha256':file_digest(ROOT/BASE),
        'manifest_sha256':file_digest(ROOT/MANIFEST),'lock_sha256':file_digest(ROOT/'uv.lock'),
        'profile_sha256':profile['sha256'],'horizon_ticks':36,'n_envs':8,
        'training_steps':STEPS,'training_seconds':4500,'evaluation_games':192,
        'evaluation_seconds':3600 if arm=='control' else 10800,
        'evaluation_qualification_reserve_seconds':120,'cleanup_reserve_seconds':60,
        'schedule_horizon':999424,'evaluation_points':[0,STEPS],
        'serial_order':[[a,s] for a,s in ORDER],
        'automatic_retry':False,'fresh_initialization_only':True,'demonstration_seed':22}


def load_hybrid_protocol(path,manifest):
    from tank_game.learning.safety_encoding import SafetyObservationEncoder
    raw=read_json(path)
    try:
        arm=raw['arm']
        if not _exact(raw,candidate(arm)):
            raise ValueError('H3 frozen identity/budget/order drift')
        p=load_protocol(ROOT/BASE,manifest)
        profile=SafetyObservationEncoder(arm).identity()
        p.update(kind='hybrid-safety-h3',protocol_id='public-safety-h3-'+arm,
                 freeze_stage='h3-frozen',seeds=[11,22,33])
        p['contracts'].update(learning=safety_learning_contract(arm),safety_profile=profile)
        p['network']['prediction_features']=arm=='features'
        p['ppo']['learning_rate'].update(schedule='linear-to-zero-over-explicit-schedule-horizon',
                                          horizon_transitions=999424)
        pool=raw['evaluation_seconds']
        p['budgets'].update(per_seed_transitions=STEPS,per_seed_complete_updates=61,
            training_wall_seconds_per_seed=4500,active_training_cutoff_seconds_per_seed=4440,
            training_wall_seconds_all_seeds=13500,evaluation_wall_seconds_all_seeds=pool,
            evaluation_active_cutoff_seconds_all_seeds=pool-180,
            evaluation_qualification_reserve_seconds=120,cleanup_reserve_seconds=60)
        p['evaluation'].update(split='validation',condition_ids=[c['id'] for c in manifest['splits']['validation']],
            checkpoint_aggregate_transitions=[0,STEPS],checkpoint_update_indices=[0,61],
            games_per_checkpoint=32,mandatory_games_all_seeds=192,
            predictor_identity='public-safety-h3-'+arm)
        p['_runtime']={'path':str(Path(path).resolve()),'sha256':file_digest(path)}
        checkpoint_observation_size(p)
        return p
    except (KeyError,TypeError,AttributeError) as error:
        raise ValueError('malformed H3 protocol') from error


def hybrid_training_target(protocol,initial_steps):
    if (protocol.get('kind')!='hybrid-safety-h3' or checkpoint_observation_size(protocol)!=358
            or type(initial_steps) is not int or not 0<=initial_steps<=STEPS or initial_steps%4096):
        raise ValueError('H3 requires fresh or latest complete same-experiment update below fixed endpoint')
    return STEPS


def confirmed_manual_interruption(result):
    """Supervisor intent and clean shutdown are separate from worker diagnostics."""
    reason=result.get('supervisor_stop_reason',result.get('stop_reason'))
    worker=result.get('worker',{})
    diagnostic=worker.get('stop_reason')
    return (result.get('status')=='incomplete' and reason=='manual-interruption'
            and not result.get('remaining_owned_pids') and not worker.get('cleanup_pending')
            and (diagnostic is None or diagnostic.startswith('KeyboardInterrupt:')))
