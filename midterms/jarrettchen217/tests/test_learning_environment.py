"""Real authoritative environment timing, outcomes and transactional resources."""
import unittest
from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch

import numpy as np

from tank_game.config import GameConfig
from tank_game.entities import BulletState
from tank_game.episodes import EpisodeSpec
from tank_game.map import GameMap, Spawn, WallEdge

try:
    from tank_game.learning.environment import TankDuelEnv
except ImportError:
    TankDuelEnv=None


def open_episode():
    edges=tuple([WallEdge('horizontal',c,r) for r in (0,6) for c in range(8)]
                +[WallEdge('vertical',c,r) for c in (0,8) for r in range(6)])
    maze=GameMap(8,6,edges,spawn=Spawn(100,100,0))
    return EpisodeSpec(maze,GameConfig(),True,(maze.spawn,Spawn(220,150,180)),120)


class LearningEnvironmentTests(unittest.TestCase):
    def setUp(self):self.assertIsNotNone(TankDuelEnv,'training environment missing')

    def make_env(self,**kwargs):
        e=TankDuelEnv((open_episode(),),**kwargs);self.addCleanup(e.close);return e

    def test_six_ticks_once_fire_and_strict_lifecycle(self):
        e=self.make_env()
        with self.assertRaises(RuntimeError):e.step(8)
        a,_=e.reset(seed=12);self.assertEqual(a.shape,(340,))
        _,r,term,trunc,info=e.step(np.int64(15)) # forward/right/fire
        self.assertEqual(info['physics_ticks'],6);self.assertFalse(term or trunc)
        self.assertEqual(r,0);self.assertEqual(e.world.observe('tank-1')['observation_tick'],6)
        self.assertEqual(e.world.observe('tank-1')['self_status']['active_bullets'],1)
        scene=e.world.observe('tank-1')
        for invalid in (True,8.0,-1,18):
            with self.assertRaises(ValueError):e.step(invalid)
            self.assertEqual(e.world.observe('tank-1'),scene)
        # Cooldown discards the second decision's shot; it is not queued/repeated.
        e.step(9);e.step(8)
        self.assertEqual(e.world.observe('tank-1')['self_status']['active_bullets'],1)
        e.close();e.close()
        with self.assertRaises(RuntimeError):e.step(8)

    def test_natural_outcome_stops_inside_interval_and_drains_only_outside_env(self):
        for seat,reward in (('tank-1',-1),('tank-2',1)):
            e=self.make_env(learner_id=seat)
            e.reset(seed=0)
            e.world._bullets=(BulletState('bullet-1',111,100,-180,0,owner_id='tank-2'),)
            _,r,terminated,truncated,info=e.step(8)
            self.assertEqual(r,reward);self.assertTrue(terminated);self.assertFalse(truncated)
            self.assertEqual(info['physics_ticks'],1)
            self.assertEqual(e.world.observe('tank-1')['round_status'],'DYING')
            before=e.world.observe('tank-1')
            for _ in range(21):e.runner.tick()
            after=e.world.observe('tank-1')
            self.assertEqual(after['round_status'],'GAME_OVER')
            self.assertEqual(before['duel'],after['duel'])
            with self.assertRaises(RuntimeError):e.step(8)

    def test_rule_draw_external_cap_and_natural_precedence(self):
        e=self.make_env();e.reset(seed=0)
        e.world._elapsed=120-1/120
        _,r,term,trunc,info=e.step(8)
        self.assertTrue(term);self.assertFalse(trunc);self.assertEqual(r,0)
        self.assertEqual(info['reason'],'time_limit')
        e=self.make_env(external_tick_limit=2);e.reset(seed=0)
        _,r,term,trunc,info=e.step(8)
        self.assertFalse(term);self.assertTrue(trunc);self.assertEqual(r,0)
        self.assertEqual(info['physics_ticks'],2);self.assertEqual(info['reason'],'external_tick_limit')
        e=self.make_env(external_tick_limit=1);e.reset(seed=0)
        e.world._bullets=(BulletState('bullet-1',111,100,-180,0),)
        _,_,term,trunc,_=e.step(8)
        self.assertTrue(term);self.assertFalse(trunc)

    def test_simultaneous_death_is_zero_reward(self):
        e=self.make_env();e.reset(seed=0)
        e.world._bullets=(BulletState('bullet-1',111,100,-180,0),
                          BulletState('bullet-2',209,150,180,0))
        _,r,term,trunc,info=e.step(8)
        self.assertTrue(term);self.assertFalse(trunc);self.assertEqual(r,0)
        self.assertEqual(info['result'],'draw')

    def test_reset_failure_preserves_rng_scene_resources_and_history(self):
        e=self.make_env();a,_=e.reset(seed=42);e.step(14)
        before=e.world.observe('tank-1');rng=deepcopy(e.np_random.bit_generator.state)
        old=e.controllers;old_history=e.encoder._result.copy()
        with (patch('tank_game.learning.environment.make_policy',side_effect=RuntimeError('factory')),
              self.assertRaisesRegex(RuntimeError,'factory')):e.reset(seed=99)
        self.assertIs(e.controllers,old);self.assertEqual(e.world.observe('tank-1'),before)
        self.assertEqual(e.np_random.bit_generator.state,rng)
        np.testing.assert_array_equal(e.encoder._result,old_history)
        b,_=e.reset(seed=42)
        self.assertEqual(e.world.observe('tank-1')['round_id'],2)
        np.testing.assert_array_equal(a,b)
        self.assertEqual(b[-1],0)
        self.assertEqual(e.world.observe('tank-1')['bullets'],[])
        c,_=e.reset(seed=42)
        np.testing.assert_array_equal(b,c)

    def test_gym_checker_and_optional_profile_validation(self):
        from gymnasium.utils.env_checker import check_env
        e=self.make_env(external_tick_limit=12)
        check_env(e,skip_render_check=True)
        with self.assertRaises(ValueError):TankDuelEnv((replace(open_episode(),round_limit=30),))
        with self.assertRaises(ValueError):e.reset(seed=True)
        with self.assertRaises(ValueError):e.reset(options={'secret':1})

    def test_info_diagnostics_are_step_deltas_and_separate_episode_totals(self):
        e=self.make_env();_,initial=e.reset(seed=0)
        decisions=[]
        for index in range(1,4):
            _,_,_,_,info=e.step(8)
            decisions.append(info['opponent_decisions'])
            self.assertEqual(info['episode_totals']['opponent_decisions'],index)
            self.assertEqual(info['failed_decisions'],0)
        self.assertEqual(decisions,[1,1,1])
        self.assertEqual(initial['opponent_decisions'],0)
        def broken(scene):raise RuntimeError('test failure')
        e.controllers['tank-2'].worker.policy.decide=broken
        for index in range(1,3):
            _,_,_,_,info=e.step(8)
            self.assertEqual(info['failed_decisions'],1)
            self.assertEqual(info['episode_totals']['failed_decisions'],index)
        _,info=e.reset(seed=0)
        self.assertTrue(all(value==0 for value in info['episode_totals'].values()))
