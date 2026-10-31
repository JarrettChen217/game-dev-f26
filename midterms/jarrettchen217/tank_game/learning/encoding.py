"""The same public340-float representation for environment and Controller use."""
from math import cos, radians, sin

import numpy as np

from tank_game.actions import Action
from tank_game.learning.contracts import public_map_bits, validate_learning_scene


class ObservationEncoder:
    def __init__(self):self.reset()

    def reset(self) -> None:
        self._round=None
        self._tick=-1
        self._dynamic=None
        self._fingerprint=None
        self._result=None

    def encode(self,scene: dict,previous_action: Action | None = None) -> np.ndarray:
        validate_learning_scene(scene)
        if previous_action is not None and not isinstance(previous_action,Action):
            raise ValueError('previous action must be Action')
        tanks={t['id']:t for t in scene['tanks']}
        self_id=scene['self_id'];other_id='tank-2' if self_id=='tank-1' else 'tank-1'
        own=tanks.get(self_id);other=tanks.get(other_id)
        values=[]
        for tank in (own,other):
            values.extend([tank['x']/256,tank['y']/192,sin(radians(tank['heading_deg'])),
                           cos(radians(tank['heading_deg'])),tank['radius']/32,1] if tank else [0]*6)
        anchor=(own['x'],own['y']) if own else (0,0)
        values.extend([(other['x']-anchor[0])/256,(other['y']-anchor[1])/192] if other else [0,0])
        bullets=sorted(scene['bullets'],key=lambda b:int(b['id'][7:]))
        for b in bullets:
            values.extend([b['x']/256,b['y']/192,(b['x']-anchor[0])/256,(b['y']-anchor[1])/192,
                           b['vx']/90,b['vy']/90,b['radius']/32,b['remaining_lifetime']/10,1])
        values.extend([0]*(9*(10-len(bullets))))
        status=scene['self_status']
        values.extend([int(status['alive']),int(status['can_fire']),status['active_bullets']/5,
                       status['cooldown_remaining']/.25,scene['duel']['elapsed']/120,
                       (120-scene['duel']['elapsed'])/120])
        values.extend(int(scene['round_status']==phase) for phase in ('PLAYING','DYING','GAME_OVER'))
        dynamic=np.asarray(values,dtype=np.float32)
        bits=public_map_bits(scene)
        action=previous_action or Action()
        fingerprint=(bits,dynamic.tobytes(),tuple(b['id'] for b in bullets),action,self_id)
        new_round=self._round!=scene['round_id']
        if not new_round and scene['observation_tick']<=self._tick:
            if scene['observation_tick']==self._tick and fingerprint==self._fingerprint:
                return self._result.copy()
            raise ValueError('conflicting duplicate or decreasing observation tick')
        prior=np.zeros(113,dtype=np.float32) if new_round else self._dynamic
        prior_action=[0,0,0] if new_round else [action.throttle,action.turn,int(action.fire)]
        result=np.concatenate([np.asarray(bits,dtype=np.float32),dynamic,prior,
                               np.asarray(prior_action+[int(not new_round)],dtype=np.float32)])
        if result.shape!=(340,) or not np.all(np.isfinite(result)) or np.any(np.abs(result)>1):
            raise ValueError('invalid tensor values')
        self._round=scene['round_id'];self._tick=scene['observation_tick']
        self._dynamic=dynamic;self._fingerprint=fingerprint;self._result=result
        return result.copy()
