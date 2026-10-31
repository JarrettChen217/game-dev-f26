"""Frozen learning conditions and thin paired evidence over the shared runtime."""
import gzip
import hashlib
import json
import math
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

from tank_game.config import GameConfig
from tank_game.contracts import make_run_contract
from tank_game.duel import legal_spawns
from tank_game.episodes import EpisodeSpec
from tank_game.evaluation import canonical, digest, revision, timing_summary
from tank_game.learning.contracts import EXECUTION_PROFILE, RULES, make_learning_contract
from tank_game.learning.environment import TankDuelEnv
from tank_game.map import Spawn, fixed_map
from tank_game.map_records import decode_map, encode_map, layout_digest, snapshot_digest
from tank_game.map_validation import validate_random_map
from tank_game.random_maps import VERSION, GeneratorOptions, generate_random_map, validate_seed
from tank_game.strategies import POLICIES

SPLITS=('train','validation','test')
SEED_STARTS=(10000,20000,30000)


def episode_from_condition(manifest,condition):
    return EpisodeSpec(decode_map(condition['map']),GameConfig(**manifest['rules']),True,
                       tuple(Spawn(**s) for s in condition['spawns']),manifest['round_limit'])


def _condition(identity,maze,spawns,*,generation=None):
    spec=EpisodeSpec(maze,GameConfig(),True,spawns,120)
    return {'id':identity,'map':encode_map(maze),'spawns':[asdict(s) for s in spawns],
            'layout_id':layout_digest(maze),'map_id':snapshot_digest(maze,spawns),
            'generation':generation,'run_contract':asdict(make_run_contract(spec))}


def make_readiness_manifest(*,counts=(64,16,32),candidate_limit=4096) -> dict:
    if (type(counts) is not tuple or len(counts)!=3 or any(type(n) is not int or n<1 for n in counts)
            or type(candidate_limit) is not int or not 1<=candidate_limit<=4096):
        raise ValueError('positive counts and bounded candidate limit required')
    maze=fixed_map();spawns=legal_spawns(maze,8,None)
    sanity=_condition('fixed-sanity',maze,spawns)
    seen={sanity['layout_id']};splits={};rejections=[]
    for split,start,count in zip(SPLITS,SEED_STARTS,counts):
        conditions=[]
        for offset in range(candidate_limit):
            seed=start+offset
            record=generate_random_map(seed)
            if record.layout_id in seen:
                rejections.append({'split':split,'seed':seed,'layout_id':record.layout_id,'reason':'duplicate_layout'})
                continue
            seen.add(record.layout_id)
            generation={'seed':record.seed,'generator_version':record.generator_version,
                        'options':asdict(record.options),'attempt':record.attempt,
                        'rejections':list(record.rejections)}
            conditions.append(_condition(f'{split}-{len(conditions)+1:03d}',record.maze,
                                         record.spawns,generation=generation))
            if len(conditions)==count:break
        if len(conditions)!=count:raise ValueError(f'{split}: exhausted candidate limit')
        splits[split]=conditions
    manifest={'schema_version':3,'kind':'learning-readiness','rules':dict(RULES),
              'round_limit':120,'decision_hz':10,'timeout':None,
              'learning_contract':asdict(make_learning_contract()),'execution_profile':EXECUTION_PROFILE,
              'opponents':{name:POLICIES[name].version for name in ('simple','hard')},
              'split_counts':dict(zip(SPLITS,counts)),'seed_starts':dict(zip(SPLITS,SEED_STARTS)),
              'candidate_limit':candidate_limit,'generation_rejections':rejections,
              'splits':splits,'sanity':[sanity]}
    validate_readiness_manifest(manifest)
    return manifest


def validate_readiness_manifest(manifest: dict) -> None:
    try:
        if (manifest['schema_version']!=3 or manifest['kind']!='learning-readiness'
                or manifest['learning_contract']!=asdict(make_learning_contract())
                or manifest['execution_profile']!=EXECUTION_PROFILE or manifest['timeout'] is not None
                or manifest['rules']!=RULES or manifest['round_limit']!=120 or manifest['decision_hz']!=10):
            raise ValueError('readiness contract mismatch')
        if manifest['opponents']!={name:POLICIES[name].version for name in ('simple','hard')}:
            raise ValueError('frozen opponent version mismatch')
        if set(manifest['splits'])!=set(SPLITS):raise ValueError('unknown splits')
        ids=set();layouts=set()
        for split,conditions in [*manifest['splits'].items(),('sanity',manifest['sanity'])]:
            if not conditions:raise ValueError('empty split')
            if split!='sanity' and len(conditions)!=manifest['split_counts'][split]:
                raise ValueError('split count mismatch')
            for c in conditions:
                spec=episode_from_condition(manifest,c)
                if c['id'] in ids or c['layout_id'] in layouts:raise ValueError('duplicate condition/layout')
                ids.add(c['id']);layouts.add(c['layout_id'])
                if c['layout_id']!=layout_digest(spec.game_map) or c['map_id']!=snapshot_digest(spec.game_map,spec.spawns):
                    raise ValueError('map identity mismatch')
                if c['run_contract']!=asdict(make_run_contract(spec)):raise ValueError('episode contract mismatch')
                if split=='sanity':
                    if c['layout_id']!=layout_digest(fixed_map()):raise ValueError('invalid fixed sanity')
                else:
                    generation=c['generation']
                    validate_seed(generation['seed'])
                    options=GeneratorOptions(**generation['options'])
                    if (generation['generator_version']!=VERSION
                            or type(generation['attempt']) is not int
                            or not 0<=generation['attempt']<options.attempt_limit
                            or len(generation['rejections'])!=generation['attempt']):
                        raise ValueError('invalid generation metadata')
                    validate_random_map(spec.game_map,8,spec.spawns)
                # Validate the public learning profile without sampling any outcomes.
                from tank_game.episodes import create_world
                from tank_game.learning.contracts import validate_learning_scene
                validate_learning_scene(create_world(spec).observe('tank-1'))
    except (KeyError,TypeError,OverflowError) as error:
        raise ValueError('malformed readiness manifest') from error


class ActionRecorder:
    """Same tick tape with optional legacy-compatible public JSON rows."""
    def __init__(self,stream=None):
        self.stream=stream;self.actions_hash=hashlib.sha256();self.frames=0

    def begin_tick(self,tick,phase):self.tick=tick;self.phase=phase;self.actions=[];self.observations={}

    def before_request(self,tank_id,scene):
        if self.phase=='PLAYING' and self.tick%6==0:self.observations[tank_id]=scene

    def after_request(self,tank_id,scene,request,*,submitted):
        if submitted:self.actions.append(request)

    def end_tick(self):
        self.actions_hash.update(canonical(self.actions).encode())
        if self.stream is not None:
            row={'kind':'step','frame':self.frames,'tick':self.tick,'actions':self.actions}
            if self.observations:row['observations']=self.observations
            self.stream.write(canonical(row)+'\n')
        self.frames+=1


def diagnostic_fault(game):
    """Worker failures are contained by the runtime, but invalidate evaluation."""
    keys=('invalid_actions','failed_decisions','rejected_decisions','disabled_worker')
    failed=[key for key in keys if game.get(key,0)]
    return 'episode diagnostics: '+', '.join(failed) if failed else None


def aggregate_readiness(games):
    valid=[g for g in games if not (g.get('fault') or diagnostic_fault(g))]
    completed=[g for g in valid if g.get('terminated')]
    wins=sum(g['result']==g['learner_id'] for g in completed)
    draws=sum(g['result']=='draw' for g in completed)
    return {'games':len(games),'completed_games':len(completed),'wins':wins,
            'losses':len(completed)-wins-draws,'draws':draws,
            'score':(wins+.5*draws)/len(completed) if completed else None,
            'external_truncations':sum(g.get('truncated',False) for g in games),
            'faults':sum(bool(g.get('fault') or diagnostic_fault(g)) for g in games),
            'rule_timeouts':sum(g.get('reason')=='time_limit' for g in completed),
            'invalid_actions':sum(g.get('invalid_actions',0) for g in games),
            'failed_decisions':sum(g.get('failed_decisions',0) for g in games),
            'rejected_decisions':sum(g.get('rejected_decisions',0) for g in games),
            'disabled_workers':sum(g.get('disabled_worker',False) for g in games)}


def run_readiness_manifest(manifest: dict,output_dir: Path,*,predictor_factory,
                           trace=False,split='validation',opponents=('simple','hard'),
                           external_tick_limit=None,predictor_version='deterministic-test-v1',
                           trace_conditions=None,predictor_metadata=None,resume=False) -> dict:
    validate_readiness_manifest(manifest)
    if (split not in (*SPLITS,'sanity') or not opponents or len(set(opponents))!=len(opponents)
            or any(o not in manifest['opponents'] for o in opponents)):
        raise ValueError('unknown split/opponents')
    conditions=manifest['sanity'] if split=='sanity' else manifest['splits'][split]
    if trace_conditions is not None and (not isinstance(trace_conditions,(tuple,list))
            or len(set(trace_conditions))!=len(trace_conditions)
            or not set(trace_conditions).issubset({c['id'] for c in conditions})):
        raise ValueError('unknown trace condition selection')
    if predictor_metadata is not None and type(predictor_metadata) is not dict:
        raise ValueError('predictor metadata must be a dictionary')
    output_dir=Path(output_dir)
    options={'trace':trace,'trace_conditions':list(trace_conditions) if trace_conditions is not None else None,
             'opponents':list(opponents),'external_tick_limit':external_tick_limit}
    games=[];history=[];report={}
    if output_dir.exists():
        if not resume or predictor_metadata is None:
            raise ValueError('will not overwrite existing evidence directory')
        if (output_dir/'report.json').exists():
            from tank_game.learning.ppo_protocol import read_json
            report=read_json(output_dir/'report.json')
            expected={'manifest_digest':digest(manifest),'split':split,'predictor_version':predictor_version,
                      'predictor_metadata':predictor_metadata,'evaluation_options':options,
                      'execution_profile':EXECUTION_PROFILE}
            if any(report.get(k)!=v for k,v in expected.items()):
                raise ValueError('incompatible resumed evaluation')
            if any(g.get('fault') and not g['fault'].startswith('RunInterrupted:') for g in report['games']):
                raise ValueError('cannot retry a faulty evaluation game')
            games=[g for g in report['games'] if not g.get('fault')
                   and (g.get('terminated') or g.get('truncated'))]
            history=list(report.get('resume_history',[]))
            archive=f'report.interrupted-{len(history)+1:03d}.json'
            (output_dir/archive).write_text((output_dir/'report.json').read_text())
            history.append({'previous_report':archive,'completed_games_reused':len(games)})
    output_dir.mkdir(parents=True,exist_ok=resume)
    conditions=manifest['sanity'] if split=='sanity' else manifest['splits'][split]
    completed={(g['condition_id'],g['opponent'],g['learner_id']) for g in games}
    order={(c['id'],o,s):i for i,(c,o,s) in enumerate(
        (c,o,s) for c in conditions for o in opponents for s in ('tank-1','tank-2'))}
    for condition in conditions:
        spec=episode_from_condition(manifest,condition)
        for opponent in opponents:
            for learner in ('tank-1','tank-2'):
                if (condition['id'],opponent,learner) in completed:continue
                env=None;stream=None;stack=ExitStack()
                game={'condition_id':condition['id'],'map_id':condition['map_id'],
                      'layout_id':condition['layout_id'],'learner_id':learner,'opponent':opponent}
                try:
                    env=TankDuelEnv((spec,),learner_id=learner,opponent=opponent,
                                   external_tick_limit=external_tick_limit)
                    observation,_=env.reset(seed=0,options={'episode_index':0})
                    predictor=predictor_factory()
                    filename=f'{condition["id"]}-{opponent}-{learner}.jsonl.gz'
                    selected_trace=trace and (trace_conditions is None or condition['id'] in trace_conditions)
                    if selected_trace:
                        if resume and (output_dir/filename).exists():
                            interrupted=output_dir/'interrupted';interrupted.mkdir(exist_ok=True)
                            retained=interrupted/f'{len(list(interrupted.iterdir()))+1:03d}-{filename}'
                            (output_dir/filename).rename(retained)
                        stream=stack.enter_context(gzip.open(output_dir/filename,'wt',encoding='utf-8'))  # noqa: SIM115 -- ExitStack closes the optional trace in finally
                        construction={k:manifest[k] for k in ('schema_version','kind','rules','round_limit')}
                        header={'kind':'header','manifest':construction,'condition':condition,
                            'readiness_manifest_digest':digest(manifest),'learning_contract':manifest['learning_contract'],
                            'public_observation_schema_version':6,'round_id':env.world.observe(learner)['round_id'],
                            'predictor_version':predictor_version,'execution_profile':EXECUTION_PROFILE}
                        if predictor_metadata is not None:header['predictor_metadata']=dict(predictor_metadata)
                        stream.write(canonical(header)+'\n')
                    recorder=ActionRecorder(stream);env.runner.recorder=recorder
                    predictions=[];search={};positions=[];stationary=0;decisions=0;action_counts=[0]*18
                    for _ in range(math.ceil(120*10)+1):
                        start=perf_counter();action=predictor(observation);predictions.append(perf_counter()-start)
                        before=env.controllers['tank-2' if learner=='tank-1' else 'tank-1'].decisions
                        observation,_,terminated,truncated,info=env.step(action);decisions+=1
                        if predictor_metadata is not None:action_counts[int(action)]+=1
                        schedule=env.controllers['tank-2' if learner=='tank-1' else 'tank-1']
                        if schedule.decisions>before:
                            for key,value in getattr(schedule.worker.policy,'search_stats',{}).items():
                                search[key]=search.get(key,0)+value
                        public=env.world.observe(learner)
                        tank=next((t for t in public['tanks'] if t['id']==learner),None)
                        if tank:
                            positions.append((tank['x'],tank['y']))
                            if len(positions)==21:
                                stationary+=all(math.hypot(x-positions[0][0],y-positions[0][1])<=.25 for x,y in positions)
                                positions=positions[-1:]
                        if terminated or truncated:break
                    else:raise RuntimeError('episode exceeded authoritative decision bound')
                    dying=0
                    while env.world.observe(learner)['round_status']=='DYING':
                        if dying>=22:raise RuntimeError('dying transition exceeded bound')
                        env.runner.tick();dying+=1
                    final=env.world.observe(learner)
                    game.update(info)
                    # Step diagnostics are deltas; evidence metrics need episode totals.
                    game.update(info['episode_totals'])
                    game.update(terminated=terminated,truncated=truncated,dying_runner_calls=dying,
                        decision_count=decisions,physics_ticks=final['observation_tick'],
                        round_seconds=final['duel']['elapsed'],stationary_windows=int(stationary),
                        self_hits=sum(e.owner_id==learner and e.tank_id==learner for e in env.world.hit_events),
                        prediction_timing=timing_summary(predictions),search_work=search,
                        opponent_timing=timing_summary(schedule.decision_seconds),
                        action_digest=recorder.actions_hash.hexdigest(),final_scene=env.world.observe('tank-1'),
                        trace=filename if selected_trace else None)
                    if predictor_metadata is not None:
                        from tank_game.learning.actions import decode_action
                        game['action_counts']=action_counts
                        game['firing_decisions']=sum(n for i,n in enumerate(action_counts) if decode_action(i).fire)
                    fault=diagnostic_fault(game)
                    if fault:game['fault']=fault
                    if stream is not None:stream.write(canonical({'kind':'footer','report':game})+'\n')
                except Exception as error:  # noqa: BLE001 -- record failed episodes separately, never invent a result
                    game['fault']=f'{type(error).__name__}: {error}'
                finally:
                    stack.close()
                    if env is not None:env.close()
                games.append(game)
                if history:games.sort(key=lambda g:order[(g['condition_id'],g['opponent'],g['learner_id'])])
                report={'schema_version':1,'manifest_digest':digest(manifest),'revision':revision(),
                        'split':split,'predictor_version':predictor_version,'execution_profile':EXECUTION_PROFILE,
                        'games':games,'aggregate':aggregate_readiness(games),
                        'limitations':['Test predictor is not a learned model or PPO result.',
                            'No wall-clock deadline; do not pool with250ms budgeted baseline.',
                            'Deterministic repeats are not independent trials; no GPU/browser parity claim.']}
                if predictor_metadata is not None:
                    report['predictor_metadata']=dict(predictor_metadata)
                    report['evaluation_options']=options
                    if history:report['resume_history']=history
                    report['limitations'][0]='Learned checkpoint artifact; this report alone is not evidence of learning.'
                temporary=output_dir/'report.json.partial'
                temporary.write_text(json.dumps(report,indent=2)+'\n')
                temporary.replace(output_dir/'report.json')
    return report


def deterministic_test_predictor(observation):
    """Exercise forward/fire capability only; not a competitive learned policy."""
    return 15
