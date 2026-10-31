"""One fixed u1900 learning-rate comparison; retained trainer and serializers."""
import hashlib
import json
import math
import os
import shutil
import time
from collections import deque
from pathlib import Path

from tank_game.laika_60hz.training.engineering import atomic_json, digest
from tank_game.laika_60hz.training.extension import compact_metric, should_publish
from tank_game.laika_60hz.training.pilot import FILES, RollingGroups, evaluate_panel, used_bytes

BASE_UPDATE, BASE_STEPS = 1900, 9363200
BASE_SHA = 'ee2344b952f41e48ce83509559d6cf783b0631ccd7d4304f47993050b4b783bb'
LIVE_SHA = '89dec5a7fdeb0f760c53ce7dd6f9071f98a45daa317f34114482861af07b7dac'
BASE_SOURCE = '9cfb06dc1e15d92d6ea836eac3676d26be923f31'
BASE_PROTOCOL = 'docs/evidence/source60-continue16-recovery-v1.json'
SSH_CAP, MAC_CAP, GROUP = 32000000, 18000000, 4400000


def scaled_rate(scheduled, arm):
    if arm not in ('a','b') or not math.isfinite(scheduled) or scheduled < 0:
        raise ValueError('invalid fixed arm/rate')
    return scheduled*(1 if arm == 'a' else .5)


def equal_update_budget(counts):
    return set(counts)=={'a','b'} and counts['a']>0 and counts['a']==counts['b']


def training_deadline(now, batch_deadline, optimization_stop):
    return min(now+5400, batch_deadline-10, optimization_stop-10)


def diagnostic_seeds(rows):
    if len(rows) != 100 or len({r['seed'] for r in rows}) != 100 or any(r['result']=='partial' for r in rows):
        raise ValueError('exact complete baseline required')
    return [r['seed'] for r in rows if r['result']=='draw'][:10]+[r['seed'] for r in rows if r['result']!='draw'][:10]


def storage_plan(ssh_bytes, mac_bytes):
    ssh_peak=ssh_bytes+3*GROUP+1500000
    mac_peak=mac_bytes+2*GROUP+100000
    plan={'existing_ssh':ssh_bytes,'existing_mac':mac_bytes,'new_ssh_group_reserves':3*GROUP,
          'new_mac_group_reserves':2*GROUP,'ssh_peak':ssh_peak,'mac_peak':mac_peak,
          'combined_peak':ssh_peak+mac_peak}
    if ssh_peak>SSH_CAP or mac_peak>MAC_CAP or plan['combined_peak']>50000000:
        raise RuntimeError('cumulative allocation cannot retain history and endpoints')
    return plan


def transition_counts(before, after, action, previous, threat, wall_sliding):
    throttle,turn,fire=action//6,(action//2)%3,action%2
    distance=math.dist(before['learner_pose'][:2],after['learner_pose'][:2])
    rotation=abs((after['learner_pose'][2]-before['learner_pose'][2]+math.pi)%(2*math.pi)-math.pi)
    moving=distance>1e-7
    return {'distance':distance,'actual_move':int(moving),'actual_turn':int(rotation>1e-7),
            'neutral_move':int(throttle==1 and turn==1),'move_command':int(throttle!=1),
            'blocked_move':int(throttle!=1 and not moving),'wall_sliding_blocked':int(throttle!=1 and not moving and wall_sliding),
            'fire_held':fire,'fire_press':int(fire and not previous%2),'fire_release':int(not fire and previous%2),
            'shots':after['shots']-before['shots'],'hits':after['hits']-before['hits'],
            'threat_frames':int(threat),'threat_and_motion':int(threat and moving)}


def trailing_counts(samples):
    result={}
    for sample in samples:
        for key,value in sample.items():
            result[key]=result.get(key,0)+value
    return result


def recycle_own_groups(root, endpoint_slot, destination):
    """Preserve current endpoint; expire only this batch's inactive rolling group."""
    root,destination=Path(root),Path(destination)
    allowed={*FILES,'checkpoint.json',*(f+'.tmp' for f in FILES),'checkpoint.json.tmp'}
    if destination.exists() or endpoint_slot not in ('slot0','slot1'):
        raise RuntimeError('endpoint destination conflict')
    # Validate ALL contents before any mutation, including foreign inactive files.
    for slot in ('slot0','slot1'):
        path=root/slot
        if path.exists() and any(not p.is_file() or p.name not in allowed for p in path.iterdir()):
            raise RuntimeError('foreign content in new rolling groups')
    groups=RollingGroups(root, root)
    marker=groups.valid(endpoint_slot)
    if marker is None:
        raise RuntimeError('complete endpoint required')
    expired={str(p.relative_to(root)):digest(p) for p in root.rglob('*') if p.is_file()}
    (root/endpoint_slot).rename(destination)
    for slot in ('slot0','slot1'):
        path=root/slot
        if path.exists():
            for p in path.iterdir():
                p.unlink()
            path.rmdir()
    (root/'latest.json').unlink(missing_ok=True)
    return {'retained':marker,'prior_new_group_files':expired,'historical_files_removed':0}


def equal(a,b):
    import numpy as np
    import torch
    if torch.is_tensor(a):
        return torch.equal(a.cpu(),b.cpu())
    if isinstance(a,np.ndarray):
        return np.array_equal(a,b)
    if isinstance(a,dict):
        return a.keys()==b.keys() and all(equal(a[k],b[k]) for k in a)
    if isinstance(a,(tuple,list)):
        return len(a)==len(b) and all(equal(x,y) for x,y in zip(a,b,strict=True))
    return a==b


def ResearchHook(context_path):
    import numpy as np
    import torch

    from tank_game.laika_60hz.training.contract import contract_digest, validate_resume_metadata

    class Hook:
        def __init__(self):
            self.c=json.loads(Path(context_path).read_text())
            self.output=Path(self.c['output'])
            self.continuing=self.c.get('continuation') in ('b-u2924-150mb','u5996-overnight-20261029')
            self.bound=None
            self.profile={'base_update':BASE_UPDATE,'base_steps':BASE_STEPS,'base_sha':BASE_SHA,
                          'base_source':BASE_SOURCE,'base_protocol':BASE_PROTOCOL,'lr_multiplier':1 if self.c['arm']=='a' else .5,
                          'ssh_cap':SSH_CAP,'log_cap':650000}
            if self.continuing:
                if self.c['continuation']=='u5996-overnight-20261029':
                    from tank_game.laika_60hz.training import overnight as bound
                else:
                    from tank_game.laika_60hz.training import b_extension as bound
                self.bound=bound
                self.profile=bound.profile(self.c)
            self.base_update,self.base_steps=self.profile['base_update'],self.profile['base_steps']
            self.groups=RollingGroups(self.c['groups'],self.c['allocation'])
            self.groups.cap=self.profile['ssh_cap']  # this specifically approved batch's frozen cumulative cap
            self.started=None
            self.control=None
            if self.continuing:
                self.control=self.bound.EvaluationControl(self)
            self.deadline=training_deadline(time.time(),self.c['batch_deadline_unix'],self.c['optimization_stop_unix'])

        def check(self):
            if self.continuing:
                return self.bound.check_budget(self.c['allocation'],self.output,now=time.time(),deadline=self.c['batch_deadline_unix'])
            if (used_bytes(self.c['allocation'])>SSH_CAP or used_bytes(self.output)>650000
                    or shutil.disk_usage(self.output).free<10*1024**3):
                raise RuntimeError('cumulative/log/free space cap')

        def restore(self,payload):
            from tank_game.laika_60hz.training import continuation16
            continuation16.validate_assets(self.c['old_assets'],self.c['batch_assets'],self.c['source_root'])
            if payload is None or digest(self.c['resume'])!=self.profile['base_sha']:
                raise ValueError('exact frozen full checkpoint required')
            state=payload['research']; validate_resume_metadata(state)
            if (state['update']!=self.base_update or state['warmup_completed']!=20
                    or state['source_head']!=self.profile['base_source'] or state['protocol_sha256']!=digest(Path(self.c['source_root'])/self.profile['base_protocol'])
                    or payload['trained_steps']!=self.base_steps or payload['schedule_steps']!=480000000
                    or state['environment_contract_sha256']!=contract_digest()):
                raise ValueError('wrong frozen lineage/progress/contract')
            if self.continuing and (state.get('lr_multiplier')!=.5 or state.get('arm')!='b'):
                raise ValueError('B half-rate provenance required')
            torch.set_rng_state(state['torch_rng'].cpu()); np.random.set_state(state['numpy_rng'])
            torch.cuda.set_rng_state_all([v.cpu() for v in state['cuda_rng']])
            self.payload=payload
            return self.base_update,20

        def before_rollout(self,batch):
            self.check()
            if batch!=4928 or time.time()>=self.deadline:
                raise SystemExit(74)

        def before_optimizer_step(self):
            if time.time()>=self.deadline:
                raise SystemExit(74)

        def metric(self,record):
            row=compact_metric(record,base_update=self.base_update,base_steps=self.base_steps)
            row['explained_variance']=float(record['explained_variance']) if math.isfinite(record['explained_variance']) else None
            return row

        def publish(self,model,optimiser,config,model_steps,update,warmup_completed,
                    save_live,save_resume,started,schedule_steps):
            self.check()
            if self.started is None:
                saved=self.payload
                checks={'model_and_critic':equal(model.state_dict(),saved['model']),
                        'Adam':equal(optimiser.state_dict(),saved['optimiser']),
                        'Torch_rng':equal(torch.get_rng_state(),saved['research']['torch_rng']),
                        'NumPy_rng':equal(np.random.get_state(),saved['research']['numpy_rng']),
                        'CUDA_rng':equal(torch.cuda.get_rng_state_all(),saved['research']['cuda_rng']),
                        'steps':model_steps==self.base_steps,'update':update==self.base_update,
                        'warmup':warmup_completed==20,'schedule':schedule_steps==480000000}
                if not all(checks.values()):
                    raise ValueError('full restore mismatch '+str(checks))
                # Change only LR prefactor AFTER exact Adam/RNG restoration proof.
                # Retained loop multiplies this by existing lineage progress; entropy uses its own unchanged coefficient.
                object.__setattr__(config,'learning_rate',scaled_rate(config.learning_rate,self.c['arm']))
                atomic_json(self.output/'restore-proof.json',{'checks':checks,'base_sha256':self.profile['base_sha'],
                            'arm':self.c['arm'],'learning_rate_prefactor':config.learning_rate,
                            'scheduled_first_lr':config.learning_rate*(1-self.base_steps/schedule_steps),
                            'idle_logit_penalty':float(model.idle_logit_penalty.detach().cpu()),
                            'pid':os.getpid()})
                self.started=time.monotonic()
                self.deadline=self.control.deadline() if self.control else training_deadline(time.time(),self.c['batch_deadline_unix'],self.c['optimization_stop_unix'])
                atomic_json(self.output/'phase.json',{'phase':'training','deadline_unix':self.deadline})
                return
            orderly=time.time()>=self.deadline-10
            endpoint=self.base_update+self.c['max_updates']
            if not should_publish(update,self.base_update,endpoint,orderly):
                return
            if warmup_completed!=20 or schedule_steps!=480000000:
                raise ValueError('schedule/warmup changed')
            if (not all(torch.isfinite(v).all() for v in model.state_dict().values())
                    or not all(not torch.is_tensor(v) or torch.isfinite(v).all() for g in optimiser.state.values() for v in g.values())):
                raise FloatingPointError('nonfinite model/Adam')
            metadata={'protocol_sha256':self.c['protocol_sha256'],'source_head':self.c['source_head'],
                      'environment_contract_sha256':contract_digest(),'update':update,'warmup_completed':20,
                      'base_resume_sha256':self.profile['base_sha'],'arm':self.c['arm'],'lr_multiplier':1 if self.c['arm']=='a' else .5,
                      'torch_rng':torch.get_rng_state(),'numpy_rng':np.random.get_state(),
                      'cuda_rng':torch.cuda.get_rng_state_all()}
            if self.control:
                metadata.update(continuation=self.c['continuation'],
                                training_seconds_accumulated=self.control.used_training(),
                                evaluation_seconds_accumulated=self.control.seconds,
                                evaluation_started_cases_accumulated=self.control.started_cases)
            def writer(path):
                save_live(path,model,config,model_steps,update,started,model_steps,schedule_steps)
                live=json.loads((path/'live.json').read_text())
                live.update(profile='source60-schema24-prep-v1',environment_contract_sha256=contract_digest())
                atomic_json(path/'live.json',live)
                save_resume(path,model,optimiser,model_steps,schedule_steps,research=metadata)
            marker=self.groups.publish(update,model_steps,20,writer)
            atomic_json(self.output/'progress.json',{**marker,'training_seconds':self.control.used_training() if self.control else time.monotonic()-self.started})
            print('COMPARISON_CHECKPOINT '+json.dumps(marker),flush=True)
            if self.control:
                return self.control.after_checkpoint(model,marker,model_steps,orderly)
            if update==endpoint or orderly:
                atomic_json(self.output/'training-stop.json',{'update':update,'steps':model_steps,
                            'training_seconds':time.monotonic()-self.started,'reason':'fixed endpoint' if update==endpoint else 'time cap'})
                raise SystemExit(75)
    return Hook()


def train(context_path):
    from tank_game.laika_60hz.training import extension, ppo
    context=json.loads(Path(context_path).read_text())
    original=ppo.DuelVec
    def recorded(*args,**kwargs):
        env=original(*args,**kwargs)
        atomic_json(Path(context['output'])/'environment-start.json',
                    {'args':list(args),'obs_sha256':hashlib.sha256(env.obs.tobytes()).hexdigest(),
                     'mask_sha256':hashlib.sha256(env.masks.tobytes()).hexdigest()})
        return env
    ppo.DuelVec=recorded
    extension.train(context_path)


def diagnostic(context):
    import torch

    from tank_game.laika_60hz.training.environment import Source60HybridEnv
    from tank_game.laika_60hz.training.ppo import ActorCritic
    torch.set_num_threads(1)
    if digest(context['model'])!=LIVE_SHA:
        raise ValueError('wrong frozen diagnostic model')
    model=ActorCritic().to('cuda')
    model.load_state_dict(torch.load(context['model'],map_location='cuda',weights_only=False)['model']); model.eval()
    rows=[json.loads(s) for s in Path(context['baseline']).read_text().splitlines()]
    if digest(context['baseline'])!='efd17663f4b96bb425d6ad52a955ec42c71c6f99f0e689dff5b1a38b093b0594':
        raise ValueError('baseline changed')
    output=Path(context['output']); selected=diagnostic_seeds(rows)
    deadline=min(time.time()+900,context['batch_deadline_unix'],context['phase_deadline_unix'])
    atomic_json(output/'phase.json',{'phase':'diagnostic','deadline_unix':deadline})
    mismatch=False
    with (output/'diagnostic.jsonl').open('x') as stream,torch.inference_mode():
        for seed in selected:
            if time.time()>=deadline:
                break
            atomic_json(output/'diagnostic.progress.json',{'started_cases':selected.index(seed)+1,'seed':seed})
            env=Source60HybridEnv(); obs,before=env.reset(seed=seed)
            counts={}; tail=deque(maxlen=300); trajectory=[]; previous=8
            result='partial'
            try:
                for tick in range(2101):
                    if time.time()>=deadline:
                        break
                    logits,_=model(torch.as_tensor(obs['features'][None],device='cuda'),torch.as_tensor(obs['mask'][None].astype(bool),device='cuda'))
                    if not torch.isfinite(logits).all():
                        raise FloatingPointError('diagnostic logits')
                    action=int(logits.argmax(-1).item())
                    threat=any(obs['mask'][i] and obs['features'][900+10*i+7]>.5 for i in range(10))
                    # SELF_OFFSET=856; +11 is physical wall_sliding (not a wall-distance heuristic).
                    obs,_reward,term,trunc,after=env.step(action)
                    sliding=bool(obs['features'][867]>.5)
                    values=transition_counts(before,after,action,previous,threat,sliding)
                    for k,v in values.items():
                        counts[k]=counts.get(k,0)+v
                    tail.append(values)
                    if tick%120==0 or term or trunc:
                        trajectory.append({'tick':tick+1,'action':action,'pose':after['learner_pose'],
                                           'opponent':after['opponent_pose'],'shots':after['shots'],
                                           'hits':after['hits'],'idle_streak':after['idle_streak'],'threat':bool(threat)})
                    previous,before=action,after
                    if term or trunc:
                        result=after['outcome']; break
                old=next(r for r in rows if r['seed']==seed)
                matches=result==old['result'] and before['tick']==old['frames']
                mismatch |= not matches
                row={'seed':seed,'result':result,'frames':before['tick'],'old_result':old['result'],
                     'matches_saved':matches,'counts':counts,'last300':trailing_counts(tail),'last_window_frames':len(tail),'trajectory':trajectory,
                     'final_state':before,'classification':'evidence only; threat+motion is not proof of successful dodge'}
                stream.write(json.dumps(row)+'\n');stream.flush()
            finally:
                env.close()
            if mismatch or result=='partial':
                break
    atomic_json(output/'diagnostic-summary.json',{'selected_seeds':selected,'valid_comparison':not mismatch,
                'new_training_updates':0,'seconds_cap':900})


def evaluate(context):
    import torch

    from tank_game.laika_60hz.training.ppo import ActorCritic
    torch.set_num_threads(1)
    model=ActorCritic().to('cuda')
    model.load_state_dict(torch.load(context['model'],map_location='cuda',weights_only=False)['model'])
    model.eval()
    return evaluate_panel(model,Path(context['output'])/'endpoint.jsonl',context['phase_deadline_unix'],context['update'],seeds=range(21000,21100))
