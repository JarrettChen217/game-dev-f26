"""Frozen paired matchups, real World episodes, and replayable public traces."""

import argparse
import gzip
import hashlib
import json
import math
import platform
import subprocess
from dataclasses import asdict
from pathlib import Path

from tank_game.agents import AgentScheduler, InlineWorker
from tank_game.config import GameConfig
from tank_game.episodes import EpisodeSpec, create_world
from tank_game.map import GameMap, Spawn, WallEdge
from tank_game.map_records import decode_map, layout_digest, snapshot_digest
from tank_game.map_validation import validate_random_map
from tank_game.navigation import map_graph
from tank_game.observation_compat import project_public_scene
from tank_game.runner import MatchRunner
from tank_game.strategies import POLICIES, make_policy
from tank_game.world import World

DECISION_HZ=10
TIME_BUDGET=.25


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def revision():
    result=subprocess.run(['git','rev-parse','HEAD'],capture_output=True,text=True,check=False,
                          cwd=Path(__file__).resolve().parent.parent)
    return result.stdout.strip() if result.returncode==0 else 'unknown'


def make_manifest():
    world=World(duel=True)
    scene=world.observe('tank-1')
    nodes,_=map_graph(scene['map'],scene['rules']['tank_radius'])
    keys=sorted(nodes)
    conditions=[]
    for i in range(30):
        a=keys[i%len(keys)]
        index=(i*7+23)%len(keys)
        b=keys[index]
        if a==b:
            b=keys[(index+1)%len(keys)]
        conditions.append({'id':f'c{i+1:02d}','seed':1000+i,
                           'spawns':[asdict(Spawn(*nodes[a],(i*37)%360)),
                                     asdict(Spawn(*nodes[b],(180+i*71)%360))]})
    # Full authoritative setup is host metadata, never inserted in policy input.
    from tank_game.map import fixed_map
    manifest={'schema_version':1,'map':asdict(fixed_map()),'rules':scene['rules'],
              'round_limit':120,'decision_hz':DECISION_HZ,'timeout':TIME_BUDGET,
              'strategies':['hard','simple'],
              'strategy_versions':{name:cls.version for name,cls in POLICIES.items()},
              'conditions':conditions,'ablation_condition_ids':[f'c{i:02d}' for i in range(1,7)],
              'seed_role':'condition identifiers only; policies and initial states are deterministic',
              'ai_use_disclosure':'Codex predeclared these legal conditions under Hao\'s S2.2 scope before match outcomes.'}
    validate_manifest(manifest)
    return manifest


def setup(manifest,condition):
    if manifest['schema_version']==3 and manifest.get('kind')!='learning-readiness':
        raise ValueError('unknown episode construction manifest')
    if manifest['schema_version'] in (2,3):
        maze = decode_map(condition['map'])
        return create_world(EpisodeSpec(maze, GameConfig(**manifest['rules']), True,
                                        tuple(Spawn(**s) for s in condition['spawns']),
                                        manifest['round_limit']))
    raw=manifest['map']
    maze=GameMap(raw['columns'],raw['rows'],tuple(WallEdge(**e) for e in raw['edges']),
                 tile_size=raw['tile_size'],wall_thickness=raw['wall_thickness'],
                 spawn=Spawn(**raw['spawn']))
    return create_world(EpisodeSpec(maze, GameConfig(**manifest['rules']), True,
                                    tuple(Spawn(**s) for s in condition['spawns']),
                                    manifest['round_limit']))


def validate_manifest(manifest):
    if manifest['schema_version'] not in (1, 2):
        raise ValueError('unsupported manifest schema')
    if (manifest['decision_hz']!=DECISION_HZ or manifest['timeout']!=TIME_BUDGET
            or manifest['rules']['tick_rate']!=60):
        raise ValueError('evaluation requires the shared 60Hz/10Hz/250ms budgets')
    if len(manifest['strategies'])!=2 or any(n not in POLICIES for n in manifest['strategies']):
        raise ValueError('select exactly two known strategies')
    ids=set()
    if not manifest['conditions']:
        raise ValueError('empty condition set')
    for condition in manifest['conditions']:
        if condition['id'] in ids:
            raise ValueError('duplicate condition identifier')
        ids.add(condition['id'])
        if manifest['schema_version'] == 2:
            from tank_game.random_maps import GeneratorOptions, validate_seed
            maze = decode_map(condition['map'])
            spawns = tuple(Spawn(**s) for s in condition['spawns'])
            validate_random_map(maze, manifest['rules']['tank_radius'], spawns)
            if (condition['map_id'] != snapshot_digest(maze, spawns)
                    or condition['layout_id'] != layout_digest(maze)):
                raise ValueError('saved map identity does not match actual snapshot')
            metadata = condition['generation']
            validate_seed(metadata['seed'])
            if metadata['seed'] != condition['seed']:
                raise ValueError('condition seed differs from generation seed')
            options = GeneratorOptions(**metadata['options'])
            if (type(metadata['attempt']) is not int
                    or not 0 <= metadata['attempt'] < options.attempt_limit
                    or type(metadata['generator_version']) is not str
                    or not metadata['generator_version']
                    or type(metadata['rejections']) not in (list, tuple)
                    or len(metadata['rejections']) != metadata['attempt']
                    or any(type(x) is not str for x in metadata['rejections'])):
                raise ValueError('invalid generation metadata')
        setup(manifest,condition)  # validate every initial condition before any game


def timing_summary(samples):
    values=sorted(samples)
    if not values:
        return {'count':0,'mean':0,'p95':0,'max':0}
    return {'count':len(values),'mean':sum(values)/len(values),
            'p95':values[max(0,math.ceil(.95*len(values))-1)],'max':values[-1]}


def _write(stream,value):
    stream.write(canonical(value)+'\n')


def response_record(value):
    try:
        canonical(value)
    except (TypeError,ValueError):
        return {'invalid_response_type':type(value).__name__}
    return value


class EvaluationRecorder:
    """Legacy trace format around the unique actual controller request."""
    def __init__(self, stream, manifest, schedules):
        self.stream, self.manifest, self.schedules = stream, manifest, schedules
        self.actions_hash = hashlib.sha256()
        self.work = {'candidates': 0, 'tank_steps': 0, 'projectile_steps': 0}
        self.raw_responses = {}
        self.positions = {tid: [] for tid in schedules}
        self.stationary_windows = {tid: 0 for tid in schedules}
        self.frame = 0

    def begin_tick(self, tick, phase):
        self.tick, self.phase = tick, phase
        self.actions, self.observed = [], {}
        self.before = {}

    def before_request(self, tank_id, public):
        if self.phase != 'PLAYING':
            return
        schedule = self.schedules[tank_id]
        if self.tick % 6 == 0 and not schedule.worker.disabled:
            self.observed[tank_id] = public
        if self.manifest['schema_version'] == 2 and self.tick % 6 == 0:
            tank = next((t for t in public['tanks'] if t['id'] == tank_id), None)
            if tank is not None:
                samples = self.positions[tank_id]
                samples.append((tank['x'], tank['y']))
                if len(samples) == 21:
                    if all(math.hypot(x-samples[0][0], y-samples[0][1]) <= .25 for x, y in samples):
                        self.stationary_windows[tank_id] += 1
                    self.positions[tank_id] = samples[-1:]
        self.before[tank_id] = schedule.decisions

    def after_request(self, tank_id, scene, request, *, submitted):
        if not submitted:
            return
        self.actions.append(request)
        schedule = self.schedules[tank_id]
        if schedule.decisions > self.before[tank_id]:
            stats = getattr(schedule.worker.policy, 'search_stats', {})
            for key in self.work:
                self.work[key] += stats.get(key, 0)
            self.raw_responses[tank_id] = response_record(schedule.worker.last_response)

    def end_tick(self):
        self.actions_hash.update(canonical(self.actions).encode())
        row = {'kind': 'step', 'frame': self.frame, 'tick': self.tick, 'actions': self.actions}
        if self.observed:
            row['observations'] = self.observed
            row['responses'] = {tid: self.raw_responses[tid] for tid in self.observed}
            row['decision_seconds'] = {tid: self.schedules[tid].decision_seconds[-1]
                                       for tid in self.observed}
        _write(self.stream, row)
        self.frame += 1


def run_game(manifest,condition,assignments,path):
    world=setup(manifest,condition)
    schedules={}
    try:
        for tank_id,name in assignments.items():
            policy=make_policy(name)
            if policy.version!=manifest['strategy_versions'][name]:
                raise ValueError('strategy version differs from the frozen manifest')
            schedules[tank_id]=AgentScheduler(InlineWorker(policy,timeout=TIME_BUDGET))
        with gzip.open(path,'wt',encoding='utf-8') as trace:
            _write(trace,{'kind':'header','manifest':manifest,'condition':condition,
                          'assignments':assignments,'revision':revision(),
                          'python':platform.python_version(),
                          'public_observation_schema_version':world.observe('tank-1')['schema_version']})
            recorder = EvaluationRecorder(trace, manifest, schedules)
            runner = MatchRunner(world, schedules, recorder=recorder)
            scene=world.observe('tank-1')
            max_steps=math.ceil(manifest['round_limit']*60)+math.ceil(
                manifest['rules']['explosion_duration']*60)+2
            for frame in range(max_steps):
                if scene['round_status']=='GAME_OVER':
                    break
                runner.tick()
                scene=world.observe('tank-1')
            if scene['round_status']!='GAME_OVER':
                raise RuntimeError('episode did not terminate within its fixed-step bound')
            events=[asdict(e) for e in world.hit_events]
            self_hits={tank_id:sum(e['owner_id']==tank_id and e['tank_id']==tank_id
                                  for e in events) for tank_id in assignments}
            elapsed=scene['duel']['elapsed']
            survival={tank_id:next((e['elapsed'] for e in events if e['tank_id']==tank_id),elapsed)
                      for tank_id in assignments}
            report={'condition_id':condition['id'],'seed':condition['seed'],
                    'initial_spawns':condition['spawns'],'assignments':assignments,
                    'result':scene['duel']['result'],'reason':'projectile_hit' if events else 'time_limit',
                    'survival_seconds':survival,'self_hits':self_hits,'hit_events':events,
                    'invalid_actions':world.rejected_actions,
                    'failed_decisions':sum(s.failures for s in schedules.values()),
                    'rejected_decisions':sum(s.rejected for s in schedules.values()),
                    'decisions':{tid:s.decisions for tid,s in schedules.items()},
                    'decision_timing':{tid:timing_summary(s.decision_seconds)
                                       for tid,s in schedules.items()},
                    'decision_seconds':{tid:list(s.decision_seconds) for tid,s in schedules.items()},
                    'disabled_workers':{tid:s.worker.disabled for tid,s in schedules.items()},
                    'search_work':recorder.work,'action_digest':recorder.actions_hash.hexdigest(),
                    'final_scene':scene,'trace':path.name}
            if manifest['schema_version'] == 2:
                report.update(map_id=condition['map_id'], layout_id=condition['layout_id'],
                              generation=condition['generation'], stationary_windows=recorder.stationary_windows)
            _write(trace,{'kind':'footer','report':report})
        return report
    finally:
        for schedule in schedules.values():
            schedule.close()


def aggregate(games):
    wins={name:0 for name in POLICIES}
    losses={name:0 for name in POLICIES}
    self_hits={name:0 for name in POLICIES}
    survived={name:[] for name in POLICIES}
    timings={name:[] for name in POLICIES}
    for game in games:
        for tid,name in game['assignments'].items():
            self_hits[name]+=game['self_hits'][tid]
            survived[name].append(game['survival_seconds'][tid])
            timings[name].extend(game['decision_seconds'][tid])
            if game['result']!='draw':
                (wins if game['result']==tid else losses)[name]+=1
    signatures=[g['action_digest'] for g in games]
    result = {'games':len(games),'unique_initial_conditions':len({canonical(
                [g['map_id'], g['initial_spawns']] if 'map_id' in g else g['initial_spawns'])
                for g in games}),
            'unique_action_traces':len(set(signatures)),
            'duplicate_action_traces':len(signatures)-len(set(signatures)),
            'wins':wins,'losses':losses,'draws':sum(g['result']=='draw' for g in games),
            'self_hits':self_hits,'mean_survival_seconds':{k:sum(v)/len(v) if v else None
                                                        for k,v in survived.items()},
            'decision_timing':{k:timing_summary(v) for k,v in timings.items()},
            'invalid_actions':sum(g['invalid_actions'] for g in games),
            'failed_decisions':sum(g['failed_decisions'] for g in games),
            'rejected_decisions':sum(g['rejected_decisions'] for g in games)}
    if any('map_id' in g for g in games):
        unique = {g['map_id']: g for g in games}
        result.update(unique_layouts=len({g['layout_id'] for g in games}),
                      generation_rejections=sum(len(g['generation']['rejections'])
                                                for g in unique.values()),
                      stationary_windows=sum(sum(g['stationary_windows'].values()) for g in games))
    return result


def run_manifest(manifest,output_dir):
    validate_manifest(manifest)
    output_dir=Path(output_dir)
    output_dir.mkdir(parents=True,exist_ok=True)
    games=[]
    for condition in manifest['conditions']:
        for swapped in (False,True):
            a,b=manifest['strategies'][::-1] if swapped else manifest['strategies']
            assignments={'tank-1':a,'tank-2':b}
            path=output_dir/f'{condition["id"]}-{int(swapped)}.jsonl.gz'
            if path.exists():
                raise ValueError(f'will not overwrite an existing trace: {path}')
            game=run_game(manifest,condition,assignments,path)
            games.append(game)
            # Incremental evidence survives an interrupted long run.
            (output_dir/'games.json').write_text(json.dumps(games,indent=2)+'\n')
    report={'manifest_digest':digest(manifest),'revision':revision(),
            'strategy_versions':manifest['strategy_versions'],
            'budget':{'physics_hz':60,'decision_hz':10,'timeout':TIME_BUDGET,
                      'candidate_limit':9,'horizon_steps':60},
            'games':games,'aggregate':aggregate(games),
            'limitations':['Deterministic conditions are not independent random trials.',
                           'Headless decisions are synchronous; GUI process startup and latency differ.',
                           'Inline timeout rejects a completed slow response, not an interruptible computation.',
                           'Survival is right-censored at episode termination, including for the winner.',
                           'No hidden state is available to policies; host self-hit attribution is separate.']}
    (output_dir/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def replay_trace(path):
    actions_hash=hashlib.sha256()
    with gzip.open(path,'rt',encoding='utf-8') as trace:
        header=json.loads(next(trace))
        world=setup(header['manifest'],header['condition'])
        declared_schema=header.get('public_observation_schema_version')
        if declared_schema is not None:
            project_public_scene(world.observe('tank-1'),schema_version=declared_schema)
        for line in trace:
            row=json.loads(line)
            if row['kind']=='footer':
                break
            for tank_id,observed in row.get('observations',{}).items():
                version=observed['schema_version']
                if declared_schema is not None and version!=declared_schema:
                    raise ValueError('observation schema differs from trace header')
                if project_public_scene(world.observe(tank_id),schema_version=version)!=observed:
                    raise ValueError('saved public observation does not match replay')
            actions_hash.update(canonical(row['actions']).encode())
            for request in row['actions']:
                world.submit_action(request['tank_id'],request)
            world.step()
    final=world.observe('tank-1')
    version=row['report']['final_scene']['schema_version']
    if declared_schema is not None and version!=declared_schema:
        raise ValueError('final observation schema differs from trace header')
    final=project_public_scene(final,schema_version=version)
    result={'final_scene':final,'action_digest':actions_hash.hexdigest()}
    if result['final_scene']!=row['report']['final_scene'] or (
            result['action_digest']!=row['report']['action_digest']):
        raise ValueError('trace outcome/digest differs from replay')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--write-manifest',action='store_true')
    parser.add_argument('--ablation',action='store_true')
    args=parser.parse_args()
    if args.write_manifest:
        args.manifest.parent.mkdir(parents=True,exist_ok=True)
        if args.manifest.exists():
            parser.error('manifest already exists; never replace frozen conditions silently')
        args.manifest.write_text(json.dumps(make_manifest(),indent=2)+'\n')
        return
    if args.output is None:
        parser.error('--output is required for evaluation')
    manifest=json.loads(args.manifest.read_text())
    if args.ablation:
        manifest['strategies']=['hard','pursuit']
        manifest['conditions']=[c for c in manifest['conditions']
                                if c['id'] in manifest['ablation_condition_ids']]
    report=run_manifest(manifest,args.output)
    print(json.dumps(report['aggregate'],indent=2))


if __name__=='__main__':
    main()
