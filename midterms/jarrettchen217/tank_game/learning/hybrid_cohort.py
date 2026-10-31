"""One serial, explicit H3 cohort; a command, never a restart/retry service."""
import json
from pathlib import Path

from tank_game.learning.hybrid_protocol import (
    ORDER,
    STEPS,
    confirmed_manual_interruption,
    load_hybrid_protocol,
)
from tank_game.learning.ppo_protocol import ROOT, _exact, file_digest, read_json


def protocol_paths():
    return {a:ROOT/f'data/learning/hybrid-safety-h3/{a}.json' for a in ('control','features')}


def phase_order():
    phases=[]
    for arm,seed in ORDER:
        phases.append({'kind':'train','arm':arm,'seed':seed,'steps':STEPS})
        phases.extend({'kind':'evaluate','arm':arm,'seed':seed,'steps':s} for s in (0,STEPS))
    phases.extend({'kind':'qualify','arm':a,'seed':22,'steps':STEPS} for a in ('control','features'))
    return phases


def cohort_identity(revision,branch):
    manifest=read_json(ROOT/'data/learning/readiness-v1/suite.json')
    paths=protocol_paths()
    for path in paths.values():load_hybrid_protocol(path,manifest)
    return {'schema_version':1,'kind':'hybrid-safety-h3-cohort','revision':revision,'branch':branch,
        'protocol_sha256':{arm:file_digest(path) for arm,path in paths.items()},
        'lock_sha256':file_digest(ROOT/'uv.lock'),'phases':phase_order(),
        'new_runtime_cap_seconds':41400,'training_submitted_cap':1499136,
        'closed_h2_seconds':236.766270827,'closed_h2_submitted':16384,'closed_h2_games':8}


def initial_checkpoint(state,seed):
    attempts=state['seeds'][str(seed)]['attempts']
    path=Path(attempts[0]['output'])/'checkpoint-000000000'
    if not path.is_dir():raise ValueError('missing fresh initial checkpoint')
    return path


def verify_pair_initialization(root,seed):
    import numpy as np
    initial=[]
    for arm in ('control','features'):
        state=read_json(Path(root)/arm/'experiment.json')
        cp=initial_checkpoint(state,seed)
        metadata=read_json(cp/'metadata.json')
        if (metadata['seed']!=seed or metadata['sampled_steps']!=0 or metadata['run_mode']!='hybrid-pilot'
                or metadata['model_state_summary']['optimizer_step_max']!=0
                or metadata['model_state_summary']['completed_updates']!=0):
            raise ValueError('nonfresh paired initialization')
        initial.append((cp,metadata))
    if initial[0][1]['model_state_summary']['policy_weights_sha256']!=initial[1][1]['model_state_summary']['policy_weights_sha256']:
        raise ValueError('paired initial weights differ')
    with np.load(initial[0][0]/'predictions.npz',allow_pickle=False) as c, np.load(initial[1][0]/'predictions.npz',allow_pickle=False) as f:
        if not np.array_equal(c['probabilities'],f['probabilities']):raise ValueError('paired initial probabilities differ')
    return {'seed':seed,'policy_weights_sha256':initial[0][1]['model_state_summary']['policy_weights_sha256'],
            'identical_prediction_probabilities':True}


def cumulative_cost(root):
    seconds=0.;steps=0;arms={}
    for arm in ('control','features'):
        folder=Path(root)/arm;train=0.;submitted=0;spent=0.
        if (folder/'experiment.json').exists():
            for seed in read_json(folder/'experiment.json')['seeds'].values():
                train+=seed['training_seconds'];submitted+=seed['sampled_total']
                if seed['training_seconds']>4500 or seed['sampled_total']>STEPS:
                    raise ValueError('per-seed cumulative budget exceeded')
        if (folder/'evaluation-budget.json').exists():spent=read_json(folder/'evaluation-budget.json')['spent_seconds']
        if spent>(3600 if arm=='control' else 10800):raise ValueError('shared arm pool exceeded')
        arms[arm]={'training_seconds':train,'evaluation_seconds':spent,'submitted_decisions':submitted}
        seconds+=train+spent;steps+=submitted
    if seconds>41400 or steps>1499136:raise ValueError('new research aggregate cap exceeded')
    return {'arms':arms,'new_seconds':seconds,'new_submitted_decisions':steps,
            'with_closed_h2_seconds':seconds+236.766270827,'with_closed_h2_submitted':steps+16384}


def run_cohort(root,*,expected_revision,resume=False):
    import fcntl

    from tank_game.learning.hybrid_evaluation import evaluate_hybrid_checkpoint, qualify_hybrid_arm
    from tank_game.learning.ppo_training import _atomic_json, _git, _snapshot, train_run
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True)
    head=_snapshot(expected_revision);branch=_git('branch','--show-current')
    if branch!='feat/ppo-feasibility-pipeline':raise ValueError('dedicated development branch required')
    identity=cohort_identity(head,branch);path=root/'cohort.json'
    with (root/'cohort.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if path.exists():
            state=read_json(path)
            if not resume or not _exact(state['identity'],identity):raise ValueError('explicit same frozen cohort continuation required')
            if state['status']!='interrupted':raise ValueError('only confirmed manual interruption may continue; no automatic fault retry')
        else:
            if resume:raise ValueError('no existing cohort to continue')
            state={'identity':identity,'status':'new','phases':[],'initialization_pairs':[]}
        for index,phase in enumerate(identity['phases']):
            _snapshot(head);cumulative_cost(root)
            if index<len(state['phases']):
                old=state['phases'][index]
                if old['status']=='complete':
                    if old['result_sha256']!=file_digest(Path(old['output'])/'result.json'):
                        raise ValueError('completed phase evidence changed')
                    continue
                if old['status']!='interrupted':raise ValueError('prior phase unconfirmed or faulted')
                continuing=True;attempt=old['attempt']+1
            else:continuing=False;attempt=0
            arm=phase['arm'];seed=phase['seed'];steps=phase['steps'];folder=root/arm
            output=folder/'attempts'/f'{index:02d}-{phase["kind"]}-{seed}-{steps}-{attempt}'
            record=dict(phase,index=index,attempt=attempt,output=str(output),status='running')
            if continuing:
                record['prior_attempts']=state['phases'][index].get('prior_attempts',[])+[state['phases'][index]]
                state['phases'][index]=record
            else:state['phases'].append(record)
            state['status']='running';_atomic_json(path,state)
            try:
                ppath=protocol_paths()[arm]
                if phase['kind']=='train':
                    checkpoint=None
                    if continuing:
                        from tank_game.learning.ppo_recovery import Experiment
                        p=load_hybrid_protocol(ppath,read_json(ROOT/'data/learning/readiness-v1/suite.json'))
                        with Experiment(folder,p,mode='hybrid-pilot',lock_sha256=identity['lock_sha256']) as journal:
                            checkpoint=journal.latest_checkpoint(seed)
                    result=train_run(ppath,ROOT/'data/learning/readiness-v1/suite.json',output,
                        seed=seed,mode='hybrid-pilot',resume=checkpoint,expected_revision=head,experiment=folder)
                    if result['status']=='complete':
                        other=root/('features' if arm=='control' else 'control')/'experiment.json'
                        if other.exists() and read_json(other)['seeds'].get(str(seed),{}).get('status')=='complete':
                            state['initialization_pairs'].append(verify_pair_initialization(root,seed))
                elif phase['kind']=='evaluate':
                    experiment=read_json(folder/'experiment.json')
                    checkpoint=(initial_checkpoint(experiment,seed) if steps==0 else
                                Path(experiment['seeds'][str(seed)]['last_checkpoint']))
                    result=evaluate_hybrid_checkpoint(checkpoint,ppath,folder,output,seed=seed,steps=steps,
                        expected_revision=head,resume=continuing)
                else:
                    result=qualify_hybrid_arm(ppath,folder,output,expected_revision=head,resume=continuing)
                record['result_sha256']=file_digest(output/'result.json')
                record['status']=('complete' if result['status']=='complete' else
                    'interrupted' if confirmed_manual_interruption(result) else 'failed')
                record['stop_reason']=result.get('stop_reason')
                state['cost']=cumulative_cost(root)
                if record['status']!='complete':
                    state['status']=record['status'];_atomic_json(path,state)
                    return state
                _atomic_json(path,state)
                print(json.dumps({'phase':index,'arm':arm,'seed':seed,'kind':phase['kind'],
                                  'status':'complete','cost':state['cost']}),flush=True)
            except BaseException as error:
                record.update(status='unconfirmed',error=f'{type(error).__name__}: {error}')
                state['status']='unconfirmed';_atomic_json(path,state)
                raise
        state['status']='complete';state['cost']=cumulative_cost(root);_atomic_json(path,state)
        return state
