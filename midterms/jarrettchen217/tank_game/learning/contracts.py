"""Learning compatibility and public profile validation; no optional imports."""
import hashlib
import json
from dataclasses import asdict, dataclass
from functools import lru_cache
from math import isfinite

from tank_game.config import GameConfig

RULES=asdict(GameConfig())
EXECUTION_PROFILE='inline-deterministic-no-deadline-v1'


@dataclass(frozen=True)
class LearningContract:
    profile: str = 'duel-default-8x6-v1'
    observation_schema: str = 'tank-obs-v1'
    action_codec: str = 'tank-action-v1'
    observation_size: int = 340
    history_frames: int = 2
    public_observation_schema_version: int = 6
    rules_version: str = 'tank-rules-v1'
    action_schema_version: int = 1
    physics_hz: int = 60
    decision_hz: int = 10
    config_digest: str = ''


def make_learning_contract() -> LearningContract:
    raw=json.dumps(RULES,sort_keys=True,separators=(',',':'),allow_nan=False)
    return LearningContract(config_digest=hashlib.sha256(raw.encode()).hexdigest())


def _number(value,low,high):
    if type(value) not in (int,float) or not isfinite(value) or not low<=value<=high:
        raise ValueError('invalid public numeric value')


@lru_cache(maxsize=64)
def _map_bits(rectangles):
    canonical=[]
    boundary=[]
    for row in range(7):
        for col in range(8):
            canonical.append((col*32,max(0,min(row*32-1,190)),32,2))
            boundary.append(row in (0,6))
    for row in range(6):
        for col in range(9):
            canonical.append((max(0,min(col*32-1,254)),row*32,2,32))
            boundary.append(col in (0,8))
    present=set(rectangles)
    if len(present)!=len(rectangles) or not present.issubset(canonical):
        raise ValueError('noncanonical or duplicate public walls')
    bits=tuple(int(rect in present) for rect in canonical)
    if any(required and not bit for required,bit in zip(boundary,bits)):
        raise ValueError('missing outer walls')
    return bits


def public_map_bits(scene: dict) -> tuple[int,...]:
    maze=scene['map']
    required={'columns':8,'rows':6,'tile_size':32,'wall_thickness':2,'width':256,'height':192}
    if any(type(maze[k]) is not int or maze[k]!=v for k,v in required.items()):
        raise ValueError('unsupported map profile')
    rectangles=[]
    for wall in maze['walls']:
        if set(wall)!={'x','y','width','height'}:
            raise ValueError('invalid wall fields')
        rect=tuple(wall[k] for k in ('x','y','width','height'))
        for value in rect:_number(value,0,256)
        rectangles.append(rect)
    return _map_bits(tuple(sorted(rectangles)))


def validate_learning_scene(scene: dict) -> None:
    try:
        if type(scene['schema_version']) is not int or scene['schema_version']!=6:
            raise ValueError('requires public duel schema6')
        if set(scene['rules'])!=set(RULES) or asdict(GameConfig(**scene['rules']))!=RULES:
            raise ValueError('unsupported rule configuration')
        public_map_bits(scene)
        if scene['self_id'] not in ('tank-1','tank-2'):
            raise ValueError('unknown learner')
        for key,minimum in (('round_id',1),('observation_tick',0)):
            if type(scene[key]) is not int or scene[key]<minimum:raise ValueError(key)
        if scene['observation_precision']!={'position':.125,'heading_deg':.25,'velocity':.125}:
            raise ValueError('unsupported precision')
        if scene['duel']['limit']!=120:raise ValueError('requires120s rule limit')
        _number(scene['duel']['elapsed'],0,120)
        phase=scene['round_status']
        if phase not in ('PLAYING','DYING','GAME_OVER'):raise ValueError('unknown phase')
        tanks=scene['tanks'];ids=[]
        for t in tanks:
            if t['id'] not in ('tank-1','tank-2'):raise ValueError('tank id')
            ids.append(t['id'])
            _number(t['x'],0,256);_number(t['y'],0,192);_number(t['heading_deg'],0,359.999999)
            if t['radius']!=8:raise ValueError('tank radius')
        if len(ids)!=len(set(ids)) or len(ids)>2:raise ValueError('duplicate tanks')
        result=scene['duel']['result']
        if phase=='PLAYING':
            if len(ids)!=2 or result is not None:raise ValueError('invalid playing state')
        elif result not in ('tank-1','tank-2','draw'):raise ValueError('missing terminal outcome')
        bullets=scene['bullets']
        if len(bullets)>10:raise ValueError('bullet capacity exceeds profile')
        bullet_ids=[]
        for b in bullets:
            identity=b['id']
            if (type(identity) is not str or not identity.startswith('bullet-')
                    or not identity[7:].isdigit() or int(identity[7:])<1):raise ValueError('bullet id')
            bullet_ids.append(identity)
            for key,limit in (('x',256),('y',192)):_number(b[key],0,limit)
            for key in ('vx','vy'):_number(b[key],-90,90)
            if b['radius']!=1.5:raise ValueError('bullet radius')
            _number(b['remaining_lifetime'],0,10)
        if len(set(bullet_ids))!=len(bullet_ids):raise ValueError('duplicate bullets')
        own=scene['self_status']
        if type(own['alive']) is not bool or own['alive']!=(scene['self_id'] in ids):
            raise ValueError('inconsistent alive flag')
        if type(own['active_bullets']) is not int or not 0<=own['active_bullets']<=min(5,len(bullets)):
            raise ValueError('own bullet count')
        _number(own['cooldown_remaining'],0,.25)
        eligible=own['alive'] and phase=='PLAYING' and own['cooldown_remaining']==0 and own['active_bullets']<5
        if type(own['can_fire']) is not bool or own['can_fire']!=eligible:
            raise ValueError('inconsistent firing eligibility')
    except (KeyError,TypeError,OverflowError) as error:
        raise ValueError('malformed learning observation') from error
