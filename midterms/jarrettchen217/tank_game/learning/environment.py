"""Single learner adapter around the authoritative fixed-step runtime."""
from copy import deepcopy
from dataclasses import asdict
from typing import ClassVar

import gymnasium as gym
import numpy as np

from tank_game.agents import AgentScheduler, InlineWorker
from tank_game.contracts import make_run_contract
from tank_game.controllers import BufferedController
from tank_game.episodes import EpisodeSpec, create_world
from tank_game.learning.actions import decode_action
from tank_game.learning.contracts import (
    EXECUTION_PROFILE,
    make_learning_contract,
    validate_learning_scene,
)
from tank_game.learning.encoding import ObservationEncoder
from tank_game.runner import MatchRunner
from tank_game.strategies import make_policy


def _close(controllers):
    for controller in controllers.values():controller.close()


class TankDuelEnv(gym.Env):
    metadata: ClassVar[dict]={'render_modes':[]}

    def __init__(self,episodes: tuple[EpisodeSpec,...],*,learner_id='tank-1',
                 opponent='simple',external_tick_limit: int | None = None,safety_arm=None):
        if not episodes or type(episodes) is not tuple:raise ValueError('nonempty tuple of episodes required')
        if learner_id not in ('tank-1','tank-2') or opponent not in ('simple','hard','laika'):
            raise ValueError('unknown learner/opponent')
        if external_tick_limit is not None and (type(external_tick_limit) is not int or external_tick_limit<=0):
            raise ValueError('external tick limit must be a positive integer')
        for episode in episodes:
            if not isinstance(episode,EpisodeSpec):raise TypeError('expected EpisodeSpec')
            validate_learning_scene(create_world(episode).observe('tank-1'))
        self.episodes=episodes;self.default_learner_id=learner_id;self.learner_id=learner_id
        self.opponent=opponent;self.external_tick_limit=external_tick_limit
        self.action_space=gym.spaces.Discrete(18)
        self.observation_space=gym.spaces.Box(-1,1,(340,),np.float32)
        self.world=None;self.runner=None;self.controllers={};self.encoder=None
        self._closed=False;self._done=True;self._contract=None;self._episode_index=None
        self.learning_contract=make_learning_contract()
        self.safety_arm=safety_arm
        self.safety_profile=None
        if safety_arm is not None:
            from tank_game.learning.contracts import LearningContract
            from tank_game.learning.safety_encoding import SafetyObservationEncoder
            from tank_game.learning.safety_protocol import safety_learning_contract
            self.safety_profile=SafetyObservationEncoder(safety_arm).identity()
            self.learning_contract=LearningContract(**safety_learning_contract(safety_arm))
            self.observation_space=gym.spaces.Box(-1,1,(358,),np.float32)

    def reset(self,*,seed: int | None = None,options: dict | None = None):
        if self._closed:raise RuntimeError('environment closed')
        if seed is not None and (type(seed) is not int or seed<0):raise ValueError('nonnegative integer seed required')
        options={} if options is None else options
        if type(options) is not dict or set(options)-{'episode_index','learner_id'}:
            raise ValueError('unknown reset options')
        learner=options.get('learner_id',self.default_learner_id)
        if learner not in ('tank-1','tank-2'):raise ValueError('unknown learner')
        index=options.get('episode_index')
        if index is not None and (type(index) is not int or not 0<=index<len(self.episodes)):
            raise ValueError('invalid episode index')
        backup=(self._np_random,self._np_random_seed)
        candidate={}
        try:
            super().reset(seed=seed)
            rng=deepcopy(self.np_random)
            rng_seed=self._np_random_seed
            index=int(rng.integers(len(self.episodes))) if index is None else index
            spec=self.episodes[index]
            prepared_world=create_world(spec)
            public=prepared_world.observe(learner)
            # Prepare the exact next round's detached view before committing restart.
            if self.world is not None:public['round_id']=self.world.observe(learner)['round_id']+1
            if self.safety_arm is None:
                encoder=ObservationEncoder()
            else:
                from tank_game.learning.safety_encoding import SafetyObservationEncoder
                encoder=SafetyObservationEncoder(self.safety_arm)
            observation=encoder.encode(public)
            contract=make_run_contract(spec)
            candidate[learner]=BufferedController()
            other='tank-2' if learner=='tank-1' else 'tank-1'
            policy=make_policy(self.opponent)
            candidate[other]=AgentScheduler(InlineWorker(policy,timeout=None),
                                             decision_hz=getattr(policy,'decision_hz',10))
            candidate={tid:candidate[tid] for tid in ('tank-1','tank-2')}
            world=self.world if self.world is not None else prepared_world
            runner=MatchRunner(world,candidate)
            if self.world is not None and not world.restart(game_map=spec.game_map,
                    spawns=spec.spawns,allow_active=True):raise RuntimeError('restart refused')
        except Exception:
            _close(candidate)
            self._np_random,self._np_random_seed=backup
            raise
        old=self.controllers
        self.world=world;self.runner=runner;self.controllers=candidate;self.encoder=encoder
        self.learner_id=learner;self._contract=contract;self._episode_index=index
        self._np_random=rng;self._np_random_seed=rng_seed;self._done=False
        _close(old)
        return observation,self._info(self.world.observe(learner),ticks=0,seconds=0,reason=None)

    def _diagnostics(self):
        other='tank-2' if self.learner_id=='tank-1' else 'tank-1'
        opponent=self.controllers[other]
        return {'invalid_actions':self.world.rejected_actions,'failed_decisions':opponent.failures,
                'rejected_decisions':opponent.rejected,'opponent_decisions':opponent.decisions}

    def _info(self,scene,*,ticks,seconds,reason,previous=None):
        other='tank-2' if self.learner_id=='tank-1' else 'tank-1'
        opponent=self.controllers[other]
        totals=self._diagnostics()
        deltas={key:value-(previous or {}).get(key,0) for key,value in totals.items()}
        return {'physics_ticks':ticks,'simulation_seconds':seconds,'reason':reason,
                'result':scene['duel']['result'],
                'observation_tick':scene['observation_tick'],'learner_id':self.learner_id,
                'episode_index':self._episode_index,'execution_profile':EXECUTION_PROFILE,
                'opponent':self.opponent,'opponent_version':opponent.worker.policy.version,
                'opponent_decision_hz':opponent.decision_hz,
                'run_contract':asdict(self._contract),'learning_contract':asdict(self.learning_contract),
                **deltas,'episode_totals':totals,
                'disabled_worker':opponent.worker.disabled,
                'hit_events':[asdict(event) for event in self.world.hit_events],
                **({'safety_profile':{'arm':self.safety_arm,'sha256':self.safety_profile['sha256']}}
                   if self.safety_profile is not None else {})}

    def step(self,action):
        if self._closed or self.world is None or self._done:
            raise RuntimeError('reset an open environment before stepping')
        if isinstance(action,np.integer):action=int(action)
        decoded=decode_action(action)
        before=self.world.observe(self.learner_id)
        previous=self._diagnostics()
        self.controllers[self.learner_id].set_input(decoded)
        ticks=0;terminated=truncated=False;reason=None
        try:
            for _ in range(6):
                self.runner.tick();ticks+=1
                scene=self.world.observe(self.learner_id)
                if scene['round_status']!='PLAYING':
                    terminated=True
                    reason='projectile_hit' if self.world.hit_events else 'time_limit'
                    break
                if self.external_tick_limit is not None and scene['observation_tick']>=self.external_tick_limit:
                    truncated=True;reason='external_tick_limit';break
            observation=self.encoder.encode(scene,decoded)
        except Exception:
            self._done=True
            raise
        self._done=terminated or truncated
        outcome=scene['duel']['result']
        reward=(0 if outcome=='draw' else 1 if outcome==self.learner_id else -1) if terminated else 0
        info=self._info(scene,ticks=ticks,seconds=scene['duel']['elapsed']-before['duel']['elapsed'],reason=reason,
                        previous=previous)
        return observation,float(reward),terminated,truncated,info

    def close(self):
        if not self._closed:
            self._closed=True;self._done=True
            _close(self.controllers)
