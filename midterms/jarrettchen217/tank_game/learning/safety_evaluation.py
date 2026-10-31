"""Four fixed H2 Controller games, reusing the existing ledger and supervisor."""
import time
from pathlib import Path

from tank_game.learning.ppo_protocol import ROOT, _exact, file_digest, read_json
from tank_game.learning.safety_protocol import checkpoint_observation_size, load_safety_protocol


def controller_game_order(manifest,protocol):
    expected=[c['id'] for c in manifest['splits']['train'][:2]]
    if protocol['kind']!='hybrid-safety-h2' or protocol['evaluation']['condition_ids']!=expected:
        raise ValueError('H2 requires the firsttwo frozen train maps only')
    return tuple((c,seat) for c in manifest['splits']['train'][:2] for seat in ('tank-1','tank-2'))


def make_safety_controller(predictor,arm):
    from tank_game.agents import AgentScheduler, InlineWorker
    from tank_game.learning.safety_encoding import SafetyEncodedPolicy
    return AgentScheduler(InlineWorker(SafetyEncodedPolicy(predictor,arm),timeout=None))


def require_controller_checkpoint(protocol,state,checkpoint):
    metadata=read_json(Path(checkpoint)/'metadata.json')
    try:
        seed=state['seeds']['11']
        if (state['protocol_sha256']!=protocol['_runtime']['sha256'] or state['mode']!='safety-smoke'
                or seed['status']!='complete' or seed['sampled_total']!=8192
                or Path(seed['last_checkpoint']).resolve()!=Path(checkpoint).resolve()
                or metadata['experiment_id']!=state['experiment_id']
                or metadata['protocol_sha256']!=state['protocol_sha256']
                or metadata['run_mode']!='safety-smoke' or type(metadata['seed']) is not int or metadata['seed']!=11
                or type(metadata['sampled_steps']) is not int or metadata['sampled_steps']!=8192
                or type(metadata['completed_updates']) is not int or metadata['completed_updates']!=2
                or not _exact(metadata['contracts'],protocol['contracts'])
                or checkpoint_observation_size(metadata)!=358):
            raise ValueError('Controller check requires completed latest same-arm H2 experiment')
    except (KeyError,TypeError) as error:
        raise ValueError('malformed Controller checkpoint prerequisite') from error


def evaluate_safety_checkpoint(checkpoint,protocol_path,experiment,output,*,expected_revision):
    from tank_game.learning.ppo_checkpoint import _validate, checkpoint_expectations
    from tank_game.learning.ppo_recovery import Experiment
    from tank_game.learning.ppo_training import _atomic_json, _launch, _snapshot
    manifest=read_json(ROOT/'data/learning/readiness-v1/suite.json')
    p=load_safety_protocol(protocol_path,manifest)
    output=Path(output)
    if output.exists():raise FileExistsError(output)
    if not (Path(experiment)/'experiment.json').is_file():
        raise ValueError('existing completed H2 experiment required')
    head=_snapshot(expected_revision)
    with Experiment(experiment,p,mode='safety-smoke',lock_sha256=file_digest(ROOT/'uv.lock')) as journal:
        require_controller_checkpoint(p,journal.value,checkpoint)
        if journal.latest_checkpoint(11)!=Path(checkpoint).resolve():
            raise ValueError('only latest completed checkpoint may be checked')
        _validate(checkpoint,checkpoint_expectations(p))
        value=(read_json(journal.budget_path) if journal.budget_path.exists() else {
            'protocol_sha256':p['_runtime']['sha256'],'spent_seconds':0.,'events':[],
            'reserved_slots':[],'reserved_trace_games':0})
        if (value['protocol_sha256']!=p['_runtime']['sha256'] or value['reserved_slots']
                or value.get('controller_attempt')):
            raise ValueError('H2 Controller slot already attempted or incompatible; no retry')
        spent_before=value['spent_seconds']
        if type(spent_before) not in (int,float) or not 0<=spent_before<120:
            raise ValueError('invalid or exhausted Controller budget')
        request={'kind':'evaluate-safety','mode':'safety-controller','seed':11,
            'checkpoint':str(Path(checkpoint).resolve()),'protocol_path':str(Path(protocol_path).resolve()),
            'manifest_path':str((ROOT/p['manifest_path']).resolve()),'expected_revision':head,
            'branch':journal.value.get('branch') or __import__('subprocess').check_output(
                ['git','branch','--show-current'],cwd=ROOT,text=True).strip(),
            'lock_sha256':file_digest(ROOT/'uv.lock'),'protocol_sha256':p['_runtime']['sha256'],
            'evaluation_budget':str(journal.budget_path),'experiment':str(journal.root)}
        # Persist before Popen/load: even a failed startup is an attempted, charged check.
        value['controller_attempt']={'output':str(output.resolve()),'status':'running'}
        _atomic_json(journal.budget_path,value)
        started=time.monotonic()
        result=None
        try:
            result=_launch(request,output,wall_seconds=180-spent_before)
        finally:
            value=read_json(journal.budget_path)
            charged=(result['accounted_evaluation_seconds'] if result is not None
                     else time.monotonic()-started)
            overhead=max(0.,spent_before+charged-value['spent_seconds'])
            value['spent_seconds']+=overhead
            complete=result is not None and result['status']=='complete'
            value['events'].append({'seconds':overhead,'complete':complete,
                                    'kind':'supervisor-overhead'})
            value['controller_attempt']['status']=(result['status'] if result is not None else 'unconfirmed')
            _atomic_json(journal.budget_path,value)
        return result


def run_controller_games(checkpoint,manifest,output,protocol,*,budget_path,progress=None):
    from tank_game.agents import AgentScheduler, InlineWorker
    from tank_game.episodes import create_world
    from tank_game.learning.evaluation import episode_from_condition
    from tank_game.learning.ppo_checkpoint import checkpoint_expectations, load_predictor
    from tank_game.learning.ppo_training import (
        Budget,
        EvaluationLedger,
        RunInterrupted,
        _atomic_json,
    )
    from tank_game.runner import MatchRunner
    from tank_game.strategies import make_policy
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    arm=protocol['contracts']['safety_profile']['arm']
    games=[]
    report={'kind':'h2-controller-smoke','arm':arm,'protocol_sha256':protocol['_runtime']['sha256'],
            'model_sha256':None,'games':games,'complete':False,
            'limits':'Four fixed train-map/seat games only; no learning or win-rate claim.'}
    _atomic_json(output/'report.json',report)
    with EvaluationLedger(budget_path,protocol) as ledger:
        metadata=read_json(Path(checkpoint)/'metadata.json')
        report['model_sha256']=metadata['model_sha256']
        ledger.reserve(11,8192,'sanity',False,output=output,model_sha256=metadata['model_sha256'])
        if progress is not None:
            progress.update(phase='evaluation',evaluation_started_monotonic=ledger.start,
                evaluation_spent_before=ledger.value['spent_seconds'],
                evaluation_active_limit=protocol['budgets']['evaluation_active_cutoff_seconds_all_seeds'])
            _atomic_json(progress['path'],progress)
        try:
            predictor=load_predictor(checkpoint,checkpoint_expectations(protocol))
        except BaseException as error:
            report['fault']=f'{type(error).__name__}: {error}'
            _atomic_json(output/'report.json',report)
            raise
        budget=Budget(0,ledger.deadline)
        for condition,seat in controller_game_order(manifest,protocol):
            controllers={};game={'condition_id':condition['id'],'learner_id':seat,'terminated':False}
            started=time.monotonic()
            try:
                budget.check(0)
                world=create_world(episode_from_condition(manifest,condition))
                other='tank-2' if seat=='tank-1' else 'tank-1'
                controllers[seat]=make_safety_controller(predictor,arm)
                controllers[other]=AgentScheduler(InlineWorker(make_policy('simple'),timeout=None))
                controllers={tid:controllers[tid] for tid in ('tank-1','tank-2')}
                runner=MatchRunner(world,controllers)
                for _ in range(7201):
                    budget.check(0)
                    runner.tick()
                    budget.check(0)
                    if world.rejected_actions or any(c.failures or c.rejected or c.worker.disabled
                                                     for c in controllers.values()):
                        raise RunInterrupted('Controller-or-action-fault')
                    public=world.observe(seat)
                    if public['round_status']!='PLAYING':
                        game.update(terminated=True,result=public['duel']['result'],
                            physics_ticks=public['observation_tick'],round_seconds=public['duel']['elapsed'])
                        break
                else:raise RunInterrupted('authoritative-round-bound-exceeded')
                if game.get('result') not in ('tank-1','tank-2','draw'):
                    raise RunInterrupted('missing-authoritative-result')
                game.update(invalid_actions=world.rejected_actions,
                    controller_diagnostics={tid:{'decisions':c.decisions,'failures':c.failures,
                        'rejected':c.rejected,'disabled':c.worker.disabled} for tid,c in controllers.items()})
            except BaseException as error:
                game['fault']=f'{type(error).__name__}: {error}'
                raise
            finally:
                for controller in controllers.values():controller.close()
                game['wall_seconds']=time.monotonic()-started
                games.append(game);_atomic_json(output/'report.json',report)
        report['complete']=len(games)==4 and all(g['terminated'] and not g.get('fault') for g in games)
        _atomic_json(output/'report.json',report)
        if not report['complete']:raise RunInterrupted('incomplete-H2-Controller-check')
        ledger.complete(output/'report.json')
    return report
