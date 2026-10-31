"""Offline H3 audit and predeclared exploratory gates. No model loading/matches."""
import math
import statistics
from pathlib import Path

from tank_game.learning.hybrid_protocol import STEPS, load_hybrid_protocol
from tank_game.learning.ppo_protocol import ROOT, _exact, file_digest, read_json


def assess_results(rows,*,complete):
    result={'relative_benefit':None,'arms':{a:{'learning_signal':None,'readiness':None}
            for a in ('control','features')},'candidate':None}
    if not complete:return result
    if set(rows)!=set(result['arms']):raise ValueError('missing arm')
    for arm in result['arms']:
        data=rows[arm]
        if [r['seed'] for r in data]!=[11,22,33]:raise ValueError('all three fixed paired seeds required')
        for row in data:
            for key in ('initial_score','final_score','initial_win_rate','final_win_rate'):
                if type(row[key]) not in (int,float) or not math.isfinite(row[key]) or not 0<=row[key]<=1:
                    raise ValueError('invalid score/win rate')
        deltas=[r['final_score']-r['initial_score'] for r in data]
        wins=[r['final_win_rate']-r['initial_win_rate'] for r in data]
        learning=sum(d>0 for d in deltas)>=2 and statistics.median(deltas)>=.10
        ready=learning and statistics.median(r['final_score'] for r in data)>=.60 and statistics.median(wins)>0
        result['arms'][arm]={'learning_signal':learning,'readiness':ready,
            'score_deltas':deltas,'win_rate_deltas':wins,'median_score_delta':statistics.median(deltas)}
    deltas=[f['final_score']-c['final_score'] for c,f in zip(rows['control'],rows['features'])]
    wins=[f['final_win_rate']-c['final_win_rate'] for c,f in zip(rows['control'],rows['features'])]
    benefit=sum(d>0 for d in deltas)>=2 and statistics.median(deltas)>=.10 and statistics.median(wins)>0
    result.update(relative_benefit=benefit,paired_final_score_deltas=deltas,paired_final_win_rate_deltas=wins)
    c=result['arms']['control']['readiness'];f=result['arms']['features']['readiness']
    arm=('features' if benefit and f else 'control' if c else 'features' if f else None)
    if arm:result['candidate']={'arm':arm,'seed':22,'steps':STEPS}
    return result


def _aggregate(games):
    wins=sum(g['result']==g['learner_id'] for g in games)
    draws=sum(g['result']=='draw' for g in games)
    return {'wins':wins,'draws':draws,'losses':len(games)-wins-draws,
        'score':(wins+.5*draws)/len(games) if games else None,'win_rate':wins/len(games) if games else None}


def inventory(root):
    root=Path(root)
    return {str(path.relative_to(root)):file_digest(path) for path in sorted(root.rglob('*'))
            if path.is_file() and not path.is_symlink() and 'analysis' not in path.relative_to(root).parts
            and not path.name.endswith('.lock')}


def _phase_receipts(cohort):
    metadata={};qualifications={};seen=set()
    def visit(phase):
        for previous in phase.get('prior_attempts',[]):visit(previous)
        output=phase.get('output')
        if output in seen:return
        seen.add(output)
        if not phase.get('result_sha256'):return
        result_path=Path(output)/'result.json'
        if file_digest(result_path)!=phase['result_sha256']:raise ValueError('changed phase result')
        worker=read_json(result_path).get('worker',{})
        for path,sha in worker.get('checkpoint_metadata_sha256',{}).items():
            if path in metadata and metadata[path]!=sha:raise ValueError('conflicting metadata receipts')
            metadata[path]=sha
        if worker.get('qualification_sha256'):
            qualifications[output]=worker['qualification_sha256']
    for phase in cohort['phases']:visit(phase)
    return metadata,qualifications


def summarize(root):
    from tank_game.learning.hybrid_cohort import (
        cohort_identity,
        cumulative_cost,
        initial_checkpoint,
        verify_pair_initialization,
    )
    from tank_game.learning.hybrid_evaluation import validate_saved_games
    from tank_game.learning.ppo_checkpoint import checkpoint_static_expectations
    root=Path(root);cohort=read_json(root/'cohort.json');identity=cohort['identity']
    if not _exact(identity,cohort_identity(identity['revision'],identity['branch'])):
        raise ValueError('foreign cohort/source/lock/protocol configuration')
    manifest=read_json(ROOT/'data/learning/readiness-v1/suite.json')
    receipts,qreceipts=_phase_receipts(cohort)
    rows={a:[] for a in ('control','features')};cases=[];gaps=[];replays=[]
    for arm,arm_rows in rows.items():
        folder=root/arm
        p=load_hybrid_protocol(ROOT/f'data/learning/hybrid-safety-h3/{arm}.json',manifest)
        expected=checkpoint_static_expectations(p)
        state=read_json(folder/'experiment.json') if (folder/'experiment.json').exists() else None
        if state and (state['mode']!='hybrid-pilot' or state['protocol_sha256']!=p['_runtime']['sha256']
                      or state['lock_sha256']!=identity['lock_sha256']):raise ValueError('foreign experiment')
        ledger=read_json(folder/'evaluation-budget.json') if (folder/'evaluation-budget.json').exists() else None
        if ledger and ledger['protocol_sha256']!=p['_runtime']['sha256']:raise ValueError('foreign evaluation ledger')
        for seed in (11,22,33):
            seed_state=state['seeds'].get(str(seed)) if state else None
            row={'seed':seed,'initial_score':None,'final_score':None,'initial_win_rate':None,'final_win_rate':None,
                 'initial':None,'final':None,'initial_completed_games':0,'final_completed_games':0,'complete':False,
                 'training_seconds':seed_state['training_seconds'] if seed_state else 0.,
                 'was_interrupted':seed_state.get('was_interrupted',True) if seed_state else None,
                 'attempts':len(seed_state['attempts']) if seed_state else 0}
            arm_rows.append(row)
            trained=bool(seed_state and seed_state['status']=='complete')
            if not trained:gaps.append(f'{arm}/{seed}:missing final training')
            elif seed_state['sampled_total']!=STEPS:raise ValueError('unequal submitted decisions')
            try:
                initial=initial_checkpoint(state,seed) if seed_state and seed_state['attempts'] else None
            except ValueError:
                if trained:raise
                initial=None
            final=Path(seed_state['last_checkpoint']) if seed_state and seed_state.get('last_checkpoint') else None
            valid=trained
            for step,checkpoint,label in ((0,initial,'initial'),(STEPS,final,'final')):
                if checkpoint is None or (step==STEPS and not trained and read_json(checkpoint/'metadata.json')['sampled_steps']!=STEPS):
                    gaps.append(f'{arm}/{seed}/{step}:missing checkpoint');valid=False;continue
                metadata=read_json(checkpoint/'metadata.json')
                if (any(not _exact(metadata.get(k),v) for k,v in expected.items())
                        or metadata['seed']!=seed or metadata['sampled_steps']!=step or metadata['completed_updates']!=step//4096
                        or metadata['implementation_revision']!=identity['revision']
                        or metadata['experiment_id']!=state['experiment_id'] or metadata['run_mode']!='hybrid-pilot'):
                    raise ValueError('foreign source/lock/contracts/horizon or substituted checkpoint endpoint')
                receipt=receipts.get(str(checkpoint))
                if receipt is None:gaps.append(f'{arm}/{seed}/{step}:unconfirmed metadata receipt');valid=False
                elif receipt!=file_digest(checkpoint/'metadata.json'):raise ValueError('checkpoint metadata changed after supervised completion')
                for name,key in [('model.zip','model_sha256'),('predictions.npz','prediction_fixture_sha256'),('rng.json','rng_sha256')]:
                    if file_digest(checkpoint/name)!=metadata[key]:raise ValueError('corrupt model bundle')
                report_path=folder/'evaluations'/f'seed-{seed}-step-{step:09d}'/'report.json'
                if not report_path.exists():gaps.append(f'{arm}/{seed}/{step}:missing evaluation');valid=False;continue
                report=read_json(report_path)
                if (report['arm']!=arm or report['seed']!=seed or report['steps']!=step
                        or report['model_sha256']!=metadata['model_sha256'] or report['revision']!=identity['revision']
                        or report['protocol_sha256']!=p['_runtime']['sha256']):raise ValueError('foreign evaluation endpoint')
                count=validate_saved_games(report['games'],manifest,p)
                row[label+'_completed_games']=count
                row[label+'_partial_aggregate']=_aggregate(report['games'])
                for game in report['games']:cases.append({'arm':arm,'seed':seed,'steps':step,**game})
                slot=ledger.get('slots',{}).get(f'{seed}:{step}:validation',{}) if ledger else {}
                attempt=ledger.get('h3_attempts',{}).get(f'{seed}:{step}:validation',{}) if ledger else {}
                if (count!=32 or report['complete'] is not True or slot.get('complete') is not True
                        or attempt.get('status')!='complete'):
                    gaps.append(f'{arm}/{seed}/{step}:incomplete evaluation');valid=False;continue
                if slot['report_sha256']!=file_digest(report_path):raise ValueError('changed completed evaluation')
                aggregate=_aggregate(report['games']);row[label]=aggregate
                row[label+'_score']=aggregate['score'];row[label+'_win_rate']=aggregate['win_rate']
            row['complete']=valid
        qphases=[phase for phase in cohort['phases'] if phase['kind']=='qualify' and phase['arm']==arm]
        if not qphases or qphases[-1]['status']!='complete':gaps.append(f'{arm}:missing qualification')
        else:
            output=qphases[-1]['output'];qpath=Path(output)/'qualification.json'
            if qreceipts.get(output)!=file_digest(qpath):raise ValueError('qualification evidence changed or unconfirmed')
            q=read_json(qpath)
            if (q['complete'] is not True or len(q['replays'])!=12 or q['revision']!=identity['revision']
                    or q['protocol_sha256']!=p['_runtime']['sha256']):raise ValueError('foreign/incomplete replay qualification')
            wanted={(seed,cid,seat) for seed in (11,22,33) for cid in p['evaluation']['condition_ids'][:2] for seat in ('tank-1','tank-2')}
            actual={(r['seed'],r['condition_id'],r['learner_id']) for r in q['replays']}
            if actual!=wanted or len({r['path'] for r in q['replays']})!=12:raise ValueError('duplicate or foreign replay certificates')
            for replay in q['replays']:
                expected_path=folder/'evaluations'/f"seed-{replay['seed']}-step-{STEPS:09d}"/f"{replay['condition_id']}-{replay['learner_id']}.jsonl.gz"
                if Path(replay['path']).resolve()!=expected_path.resolve():raise ValueError('foreign replay path')
                if file_digest(Path(replay['path']))!=replay['sha256']:raise ValueError('changed replay trace')
            replays.extend(q['replays'])
    complete=not gaps and cohort['status']=='complete' and len(cases)==384 and len(replays)==24
    if cohort['status']!='complete':gaps.append('cohort not complete')
    pairs=[verify_pair_initialization(root,seed) for seed in (11,22,33)] if complete else []
    cost=cumulative_cost(root)
    result={'kind':'hybrid-safety-h3-summary','identity':identity,'complete':complete,'gaps':gaps,
        'rows':rows,'gates':assess_results(rows,complete=complete),'cost':cost,
        'initialization_pairs':pairs,'prescribed_games_completed':len(cases),'replays_verified':len(replays),
        'case_rows':cases,'raw_inventory':inventory(root),
        'limitations':'Three training seeds; repeated deterministic map/seat pairs are not independent trials. No holdout/GPU/cloud/GUI/course claim.'}
    candidate=result['gates']['candidate']
    if candidate:
        state=read_json(root/candidate['arm']/'experiment.json')
        result['candidate_bundle']=state['seeds']['22']['last_checkpoint']
    return result
