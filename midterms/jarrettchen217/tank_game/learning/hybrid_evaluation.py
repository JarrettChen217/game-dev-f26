"""Bounded H3 normal-Controller validation; durable attempts and case continuation."""
import gzip
import math
import time
from pathlib import Path

from tank_game.learning.hybrid_protocol import (
    STEPS,
    confirmed_manual_interruption,
    load_hybrid_protocol,
)
from tank_game.learning.ppo_protocol import ROOT, _exact, file_digest, read_json
from tank_game.learning.ppo_training import _atomic_json


def case_order(manifest,protocol):
    conditions=manifest['splits']['validation']
    if (protocol['kind']!='hybrid-safety-h3' or len(conditions)!=16
            or protocol['evaluation']['condition_ids']!=[c['id'] for c in conditions]):
        raise ValueError('H3 requires all frozen validation layouts')
    return tuple((c,seat) for c in conditions for seat in ('tank-1','tank-2'))


def selected_trace(protocol,steps,condition):
    if type(steps) is not int or steps not in (0,STEPS):
        raise ValueError('only declared initial/final endpoints')
    return steps==STEPS and condition['id'] in protocol['evaluation']['condition_ids'][:2]


def validate_saved_games(games,manifest,protocol):
    from tank_game.learning.evaluation import diagnostic_fault
    order=case_order(manifest,protocol)
    if not isinstance(games,list) or len(games)>32:raise ValueError('invalid completed case list')
    for game,(condition,seat) in zip(games,order):
        if (game.get('condition_id')!=condition['id'] or game.get('learner_id')!=seat
                or game.get('terminated') is not True or game.get('result') not in ('tank-1','tank-2','draw')
                or game.get('fault') or diagnostic_fault(game)):
            raise ValueError('foreign, duplicate, incomplete or faulty completed case')
    return len(games)


def begin_attempt(path,protocol,identity,output,*,resume):
    path=Path(path)
    value=read_json(path) if path.exists() else {'protocol_sha256':protocol['_runtime']['sha256'],
        'spent_seconds':0.,'events':[],'reserved_slots':[],'reserved_trace_games':0}
    spent=value['spent_seconds']
    cutoff=(protocol['budgets']['evaluation_wall_seconds_all_seeds']-60
            if identity.get('phase')=='qualification' else protocol['budgets']['evaluation_active_cutoff_seconds_all_seeds'])
    if (value['protocol_sha256']!=protocol['_runtime']['sha256'] or type(spent) not in (int,float)
            or not math.isfinite(spent) or not 0<=spent<cutoff):
        raise ValueError('incompatible or exhausted shared evaluation budget')
    key=('qualification' if identity.get('phase')=='qualification' else
         f"{identity['seed']}:{identity['steps']}:validation")
    slots=value.setdefault('h3_attempts',{})
    previous=slots.get(key)
    if any(k!=key and v['status']!='complete' for k,v in slots.items()):
        raise ValueError('unresolved or faulted shared-pool attempt; preserve and inspect')
    if previous is not None:
        if (not resume or previous['status']!='interrupted' or not _exact(previous['identity'],identity)):
            raise ValueError('only explicit interrupted same-model/case continuation allowed')
    elif resume:raise ValueError('no interrupted evaluation to continue')
    token={'slot':key,'index':len(previous['attempts']) if previous else 0}
    slot=previous or {'identity':identity,'attempts':[]}
    slot['attempts'].append({'output':str(Path(output).resolve()),'status':'running'})
    slot['status']='running';slots[key]=slot
    _atomic_json(path,value)
    return token


def finish_attempt(path,token,*,spent_before,charged,status):
    if type(charged) not in (int,float) or not math.isfinite(charged) or charged<0:
        raise ValueError('unknown evaluation accounting')
    value=read_json(path)
    slot=value['h3_attempts'][token['slot']]
    if len(slot['attempts'])!=token['index']+1 or slot['status']!='running':
        raise ValueError('evaluation attempt identity changed')
    # Worker EvaluationLedger already charged its own block; add all supervisor/startup/cleanup overhead.
    overhead=max(0.,spent_before+charged-value['spent_seconds'])
    value['spent_seconds']+=overhead
    value['events'].append({'kind':'h3-supervisor-overhead','seconds':overhead,'complete':status=='complete'})
    slot['status']=status
    slot['attempts'][-1].update(status=status,supervised_seconds=charged)
    _atomic_json(path,value)


def require_checkpoint(protocol,state,checkpoint,seed,steps):
    from tank_game.learning.ppo_checkpoint import _validate, checkpoint_expectations
    if type(seed) is not int or seed not in protocol['seeds'] or type(steps) is not int or steps not in (0,STEPS):
        raise ValueError('undeclared H3 seed/point')
    metadata=_validate(checkpoint,checkpoint_expectations(protocol))
    seed_state=state['seeds'].get(str(seed),{})
    attempts=seed_state.get('attempts',[])
    if (state['mode']!='hybrid-pilot' or state['protocol_sha256']!=protocol['_runtime']['sha256']
            or seed_state.get('status')!='complete' or seed_state['sampled_total']!=STEPS
            or metadata['experiment_id']!=state['experiment_id'] or metadata['run_mode']!='hybrid-pilot'
            or metadata['seed']!=seed or metadata['sampled_steps']!=steps
            or metadata['completed_updates']!=steps//4096
            or not any(Path(checkpoint).resolve().parent==Path(a['output']).resolve() for a in attempts)
            or (steps==STEPS and Path(seed_state['last_checkpoint']).resolve()!=Path(checkpoint).resolve())):
        raise ValueError('requires declared same-experiment H3 checkpoint after completed training')
    return metadata


def evaluate_hybrid_checkpoint(checkpoint,protocol_path,experiment,output,*,seed,steps,expected_revision,resume=False):
    from tank_game.learning.ppo_recovery import Experiment
    from tank_game.learning.ppo_training import _git, _launch, _snapshot
    manifest=read_json(ROOT/'data/learning/readiness-v1/suite.json')
    protocol=load_hybrid_protocol(protocol_path,manifest)
    if not (Path(experiment)/'experiment.json').is_file():raise ValueError('existing experiment required')
    output=Path(output)
    if output.exists():raise FileExistsError(output)
    head=_snapshot(expected_revision)
    with Experiment(experiment,protocol,mode='hybrid-pilot',lock_sha256=file_digest(ROOT/'uv.lock')) as journal:
        metadata=read_json(Path(checkpoint)/'metadata.json')
        games_root=journal.root/'evaluations'/f'seed-{seed}-step-{steps:09d}'
        identity={'seed':seed,'steps':steps,'model_sha256':metadata['model_sha256'],
                  'revision':head,'games_root':str(games_root)}
        token=begin_attempt(journal.budget_path,protocol,identity,output,resume=resume)
        spent_before=read_json(journal.budget_path)['spent_seconds']
        started=time.monotonic();result=None
        try:
            require_checkpoint(protocol,journal.value,checkpoint,seed,steps)
            request={'kind':'evaluate-hybrid','mode':'hybrid-evaluation','seed':seed,'steps':steps,
                'checkpoint':str(Path(checkpoint).resolve()),'games_root':str(games_root),'resume':resume,
                'protocol_path':str(Path(protocol_path).resolve()),'manifest_path':str(ROOT/protocol['manifest_path']),
                'expected_revision':head,'branch':_git('branch','--show-current'),
                'lock_sha256':file_digest(ROOT/'uv.lock'),'protocol_sha256':protocol['_runtime']['sha256'],
                'evaluation_budget':str(journal.budget_path)}
            result=_launch(request,output,wall_seconds=protocol['budgets']['evaluation_wall_seconds_all_seeds']
                           -spent_before-120-(time.monotonic()-started))
        finally:
            charged=time.monotonic()-started
            status='complete' if result and result['status']=='complete' else (
                'interrupted' if result and confirmed_manual_interruption(result) else 'failed')
            finish_attempt(journal.budget_path,token,spent_before=spent_before,charged=charged,status=status)
        return result


def run_hybrid_games(request,manifest,protocol,*,progress):
    from tank_game.actions import Action
    from tank_game.agents import AgentScheduler, InlineWorker
    from tank_game.episodes import create_world
    from tank_game.evaluation import canonical, digest, timing_summary
    from tank_game.learning.actions import encode_action
    from tank_game.learning.evaluation import (
        ActionRecorder,
        aggregate_readiness,
        episode_from_condition,
    )
    from tank_game.learning.ppo_checkpoint import checkpoint_expectations, load_predictor
    from tank_game.learning.ppo_training import Budget, EvaluationLedger, RunInterrupted
    from tank_game.learning.safety_evaluation import make_safety_controller
    from tank_game.runner import MatchRunner
    from tank_game.strategies import make_policy
    root=Path(request['games_root']);root.mkdir(parents=True,exist_ok=True)
    metadata=read_json(Path(request['checkpoint'])/'metadata.json')
    identity={'kind':'hybrid-safety-h3-validation','arm':protocol['contracts']['safety_profile']['arm'],
        'seed':request['seed'],'steps':request['steps'],'revision':request['expected_revision'],
        'protocol_sha256':protocol['_runtime']['sha256'],'model_sha256':metadata['model_sha256']}
    saved=read_json(root/'report.json') if (root/'report.json').exists() else None
    if saved is not None and (not request['resume'] or any(saved.get(k)!=v for k,v in identity.items())):
        raise ValueError('existing evaluation requires explicit same-identity continuation')
    report=saved or identity|{'games':[],'interrupted_games':[],'complete':False}
    offset=validate_saved_games(report['games'],manifest,protocol)
    _atomic_json(root/'report.json',report)
    with EvaluationLedger(request['evaluation_budget'],protocol) as ledger:
        ledger.reserve(request['seed'],request['steps'],'validation',request['steps']==STEPS,
            resume=request['resume'],output=root,model_sha256=metadata['model_sha256'])
        progress.update(phase='evaluation',evaluation_started_monotonic=ledger.start,
            evaluation_spent_before=ledger.value['spent_seconds'],
            evaluation_active_limit=protocol['budgets']['evaluation_active_cutoff_seconds_all_seeds'])
        _atomic_json(progress['path'],progress)
        predictor=load_predictor(request['checkpoint'],checkpoint_expectations(protocol))
        budget=Budget(0,ledger.deadline)
        for condition,seat in case_order(manifest,protocol)[offset:]:
            controllers={};stream=None;started=time.monotonic()
            game={'condition_id':condition['id'],'learner_id':seat,'terminated':False}
            trace=selected_trace(protocol,request['steps'],condition)
            filename=f"{condition['id']}-{seat}.jsonl.gz"
            try:
                budget.check(0)
                world=create_world(episode_from_condition(manifest,condition))
                other='tank-2' if seat=='tank-1' else 'tank-1'
                controllers[seat]=make_safety_controller(predictor,identity['arm'])
                controllers[other]=AgentScheduler(InlineWorker(make_policy('simple'),timeout=None))
                controllers={tid:controllers[tid] for tid in ('tank-1','tank-2')}
                if trace:
                    if (root/filename).exists():
                        retained=root/'interrupted';retained.mkdir(exist_ok=True)
                        (root/filename).rename(retained/f'{len(list(retained.iterdir())):03d}-{filename}')
                    stream=gzip.open(root/filename,'xt',encoding='utf-8')  # noqa: SIM115 -- closed in game finally, including failures
                    header={'kind':'header','manifest':{k:manifest[k] for k in ('schema_version','kind','rules','round_limit')},
                        'condition':condition,'readiness_manifest_digest':digest(manifest),
                        'learning_contract':protocol['contracts']['learning'],'public_observation_schema_version':6,
                        'round_id':world.observe(seat)['round_id'],'predictor_version':protocol['evaluation']['predictor_identity'],
                        'execution_profile':protocol['contracts']['execution_profile'],'predictor_metadata':identity}
                    stream.write(canonical(header)+'\n')
                recorder=ActionRecorder(stream);runner=MatchRunner(world,controllers,recorder=recorder)
                counts=[0]*18;positions=[];stationary=0;latencies=[]
                for _ in range(7201):
                    budget.check(0)
                    before=controllers[seat].decisions
                    tick_started=time.perf_counter();runner.tick()
                    if controllers[seat].decisions>before:
                        latencies.append(time.perf_counter()-tick_started)
                        request_action=next(a for a in recorder.actions if a['tank_id']==seat)
                        counts[encode_action(Action(request_action['throttle'],request_action['turn'],request_action['fire']))]+=1
                        scene=world.observe(seat)
                        tank=next((t for t in scene['tanks'] if t['id']==seat),None)
                        if tank:
                            positions.append((tank['x'],tank['y']))
                            if len(positions)==21:
                                stationary+=all(math.hypot(x-positions[0][0],y-positions[0][1])<=.25 for x,y in positions)
                                positions=positions[-1:]
                    budget.check(0)
                    if world.rejected_actions or any(c.failures or c.rejected or c.worker.disabled for c in controllers.values()):
                        raise RunInterrupted('Controller-or-action-fault')
                    final=world.observe(seat)
                    if final['round_status']!='PLAYING':break
                else:raise RunInterrupted('authoritative-round-bound-exceeded')
                if final['duel']['result'] not in ('tank-1','tank-2','draw'):
                    raise RunInterrupted('missing-authoritative-result')
                from tank_game.learning.actions import decode_action
                game.update(terminated=True,result=final['duel']['result'],reason='projectile_hit' if world.hit_events else 'time_limit',
                    physics_ticks=final['observation_tick'],round_seconds=final['duel']['elapsed'],
                    final_scene=world.observe('tank-1'),action_digest=recorder.actions_hash.hexdigest(),stationary_windows=stationary,
                    self_hits=sum(e.owner_id==seat and e.tank_id==seat for e in world.hit_events),
                    action_counts=counts,firing_decisions=sum(n for i,n in enumerate(counts) if decode_action(i).fire),
                    prediction_latency=timing_summary(latencies),latency_scope='entire-learner-decision-tick-including-Simple',
                    invalid_actions=world.rejected_actions,failed_decisions=sum(c.failures for c in controllers.values()),
                    rejected_decisions=sum(c.rejected for c in controllers.values()),
                    disabled_worker=any(c.worker.disabled for c in controllers.values()),trace=filename if trace else None)
                if stream:stream.write(canonical({'kind':'footer','report':game})+'\n')
                report['games'].append(game)
            except BaseException as error:
                game.update(interruption=f'{type(error).__name__}: {error}')
                report['interrupted_games'].append(game)
                raise
            finally:
                for c in controllers.values():c.close()
                if stream:stream.close()
                game['wall_seconds']=time.monotonic()-started
                report['aggregate']=aggregate_readiness(report['games'])
                _atomic_json(root/'report.json',report)
        report['complete']=validate_saved_games(report['games'],manifest,protocol)==32
        _atomic_json(root/'report.json',report)
        ledger.complete(root/'report.json')
    return report


def qualify_hybrid_arm(protocol_path,experiment,output,*,expected_revision,resume=False):
    """One owned replay/load qualification, charged against the reserved arm pool."""
    from tank_game.learning.ppo_training import _git, _launch, _snapshot
    manifest=read_json(ROOT/'data/learning/readiness-v1/suite.json')
    protocol=load_hybrid_protocol(protocol_path,manifest)
    head=_snapshot(expected_revision)
    experiment=Path(experiment).resolve();budget=experiment/'evaluation-budget.json'
    identity={'phase':'qualification','seed':22,'steps':STEPS,'revision':head,
              'protocol_sha256':protocol['_runtime']['sha256'],'experiment':str(experiment)}
    prior=read_json(budget).get('h3_attempts',{}).get('qualification') if budget.exists() else None
    previous_output=prior['attempts'][-1]['output'] if prior and resume else None
    token=begin_attempt(budget,protocol,identity,output,resume=resume)
    spent_before=read_json(budget)['spent_seconds'];started=time.monotonic();result=None
    try:
        request={'kind':'qualify-hybrid','mode':'hybrid-qualification','seed':22,
            'experiment':str(experiment),'protocol_path':str(Path(protocol_path).resolve()),
            'manifest_path':str(ROOT/protocol['manifest_path']),'expected_revision':head,
            'branch':_git('branch','--show-current'),'lock_sha256':file_digest(ROOT/'uv.lock'),
            'protocol_sha256':protocol['_runtime']['sha256'],'evaluation_budget':str(budget),'previous_output':previous_output}
        result=_launch(request,Path(output),wall_seconds=protocol['budgets']['evaluation_wall_seconds_all_seeds']-spent_before)
    finally:
        charged=max(time.monotonic()-started,result.get('accounted_evaluation_seconds',0.) if result else 0.)
        finish_attempt(budget,token,spent_before=spent_before,charged=charged,
            status='complete' if result and result['status']=='complete' else
                'interrupted' if result and confirmed_manual_interruption(result) else 'failed')
    return result


def run_hybrid_qualification(request,manifest,protocol):
    import copy

    from tank_game.evaluation import replay_trace
    from tank_game.learning.ppo_checkpoint import checkpoint_expectations, load_predictor
    from tank_game.learning.ppo_training import Budget, EvaluationLedger
    p=copy.deepcopy(protocol)
    p['budgets']['evaluation_active_cutoff_seconds_all_seeds']=p['budgets']['evaluation_wall_seconds_all_seeds']-60
    experiment=Path(request['experiment']);state=read_json(experiment/'experiment.json')
    evidence={'kind':'h3-arm-qualification','revision':request['expected_revision'],
        'protocol_sha256':protocol['_runtime']['sha256'],'replays':[],'complete':False}
    previous=request.get('previous_output')
    if previous:
        previous=Path(previous);prior=read_json(previous/'result.json')
        qpath=previous/'qualification.json'
        if qpath.exists():
            if prior['worker'].get('qualification_sha256')!=file_digest(qpath):
                raise ValueError('interrupted qualification evidence changed')
            saved=read_json(qpath)
            if saved['revision']!=evidence['revision'] or saved['protocol_sha256']!=evidence['protocol_sha256']:
                raise ValueError('foreign interrupted qualification')
            evidence['replays']=saved['replays']
    completed={(r['seed'],r['condition_id'],r['learner_id']):r for r in evidence['replays']}
    wanted={(seed,cid,seat) for seed in protocol['seeds'] for cid in protocol['evaluation']['condition_ids'][:2]
            for seat in ('tank-1','tank-2')}
    if len(completed)!=len(evidence['replays']) or not set(completed)<=wanted:
        raise ValueError('duplicate or foreign saved replay evidence')
    _atomic_json(Path(request['output'])/'qualification.json',evidence)
    with EvaluationLedger(request['evaluation_budget'],p) as ledger:
        budget=Budget(0,ledger.deadline)
        for seed in protocol['seeds']:
            for steps in (0,STEPS):
                budget.check(0)
                folder=experiment/'evaluations'/f'seed-{seed}-step-{steps:09d}'
                report=read_json(folder/'report.json')
                if (report.get('complete') is not True or validate_saved_games(report['games'],manifest,protocol)!=32
                        or report['protocol_sha256']!=protocol['_runtime']['sha256']
                        or report['revision']!=request['expected_revision'] or report['seed']!=seed or report['steps']!=steps):
                    raise ValueError('qualification requires all six same-source evaluation reports')
                slot=ledger.value['slots'][f'{seed}:{steps}:validation']
                if not slot['complete'] or slot['report_sha256']!=file_digest(folder/'report.json'):
                    raise ValueError('evaluation report changed after completion')
                for game in report['games']:
                    expected_trace=selected_trace(protocol,steps,{'id':game['condition_id']})
                    if bool(game.get('trace'))!=expected_trace:raise ValueError('trace selection drift')
                    if not expected_trace:continue
                    budget.check(0)
                    path=folder/game['trace']
                    if path.is_symlink() or path.parent!=folder:raise ValueError('foreign trace path')
                    key=(seed,game['condition_id'],game['learner_id'])
                    if key in completed:
                        saved=completed[key]
                        if saved['path']!=str(path) or saved['sha256']!=file_digest(path) or saved['action_digest']!=game['action_digest']:
                            raise ValueError('saved replay identity changed')
                        continue
                    replay=replay_trace(path)
                    if replay['action_digest']!=game['action_digest'] or replay['final_scene']!=game['final_scene']:
                        raise ValueError('trace/report mismatch')
                    evidence['replays'].append({'path':str(path),'sha256':file_digest(path),
                        'action_digest':replay['action_digest'],'seed':seed,'condition_id':game['condition_id'],
                        'learner_id':game['learner_id']})
                    _atomic_json(Path(request['output'])/'qualification.json',evidence)
                    budget.check(0)
        checkpoint=Path(state['seeds']['22']['last_checkpoint'])
        metadata=require_checkpoint(protocol,state,checkpoint,22,STEPS)
        load_predictor(checkpoint,checkpoint_expectations(protocol))
        budget.check(0)
        evidence.update(complete=len(evidence['replays'])==12,candidate_seed22_model_sha256=metadata['model_sha256'],
                        candidate_checkpoint=str(checkpoint))
        if not evidence['complete']:raise ValueError('missing declared trace replays')
        _atomic_json(Path(request['output'])/'qualification.json',evidence)
    return evidence
