"""Explicit H1 opt-in observation adapters; old340 routes stay unchanged."""
import hashlib
import json
from pathlib import Path

import numpy as np

from tank_game.actions import Action
from tank_game.learning.contracts import public_map_bits, validate_learning_scene
from tank_game.learning.encoding import ObservationEncoder
from tank_game.learning.policy import EncodedPolicy
from tank_game.learning.safety import SafetyForecast


def _public_key(scene,previous_action):
    # Keep exact public lifetime/cooldown values before float32 conversion.
    # Unknown host fields/ownership/effects never enter this fingerprint.
    tanks=tuple(sorted(tuple(t[k] for k in ('id','x','y','heading_deg','radius'))
                       for t in scene['tanks']))
    bullets=tuple(sorted(tuple(b[k] for k in ('id','x','y','vx','vy','radius','remaining_lifetime'))
                         for b in scene['bullets']))
    status=tuple(scene['self_status'][k] for k in ('alive','active_bullets','cooldown_remaining','can_fire'))
    duel=tuple(scene['duel'][k] for k in ('elapsed','limit','result'))
    return public_map_bits(scene),scene['self_id'],tanks,bullets,status,duel,scene['round_status'],previous_action


class SafetyObservationEncoder:
    def __init__(self,arm:str):
        self._base=ObservationEncoder()
        self._forecast=SafetyForecast()
        self.set_arm(arm)

    def set_arm(self,arm:str)->None:
        if type(arm) is not str or arm not in ('control','features'):
            raise ValueError('expected control or features arm')
        self.arm=arm
        self.reset()

    def reset(self)->None:
        self._base.reset()
        self._round=None
        self._tick=-1
        self._key=None
        self._result=None

    def identity(self)->dict:
        root=Path(__file__).resolve().parents[2]
        paths=('tank_game/learning/safety_encoding.py','tank_game/learning/encoding.py',
               'tank_game/learning/policy.py','tank_game/learning/safety_initialization.py')
        source={p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths}
        identity={'profile':'duel-public-safety-v1','observation_schema':'tank-obs-safety-v1',
                  'arm':self.arm,'observation_size':358,'base_observation_size':340,
                  'action_codec':'tank-action-v1','network':{'pi':[128,128],'vf':[128,128]},
                  'initialization':'zero-added-input-columns-actor-and-critic-v1',
                  'provider':self._forecast.identity(),'adapter_source_sha256':source}
        identity['sha256']=hashlib.sha256(json.dumps(identity,sort_keys=True,
                                        separators=(',',':')).encode()).hexdigest()
        return identity

    def encode(self,scene,previous_action=None)->np.ndarray:
        validate_learning_scene(scene)
        if previous_action is not None and not isinstance(previous_action,Action):
            raise ValueError('previous action must be Action')
        key=_public_key(scene,previous_action)
        if self._round==scene['round_id'] and scene['observation_tick']<=self._tick:
            if scene['observation_tick']==self._tick and key==self._key:
                return self._result.copy()
            raise ValueError('conflicting duplicate or decreasing safety observation tick')
        # Forecast errors cannot partially advance history; reset/arm change clears the cache.
        tail=(self._forecast.features(scene) if self.arm=='features'
              else np.zeros(18,dtype=np.float32))
        base=self._base.encode(scene,previous_action)
        result=np.concatenate((base,tail))
        self._round=scene['round_id'];self._tick=scene['observation_tick']
        self._key=key;self._result=result
        return result.copy()


class SafetyEncodedPolicy(EncodedPolicy):
    version='encoded-safety-prototype-v1'

    def __init__(self,predict,arm:str):
        super().__init__(predict)
        self.encoder=SafetyObservationEncoder(arm)

    def set_arm(self,arm:str)->None:
        self.encoder.set_arm(arm)
        self._round=None
        self._tick=None
        self._previous=None
        self._input_previous=None
        self._response=None
