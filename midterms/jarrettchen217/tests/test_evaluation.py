"""Evaluation records real actions, paired conditions and host-only attribution."""

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from tank_game.agents import AgentScheduler, InlineWorker
from tank_game.controllers import keyboard_request
from tank_game.entities import BulletState
from tank_game.evaluation import make_manifest, replay_trace, run_manifest, validate_manifest
from tank_game.world import World
from tests.test_duel import duel


class Idle:
    version='test-idle-v1'

    def decide(self,scene):
        return keyboard_request(scene,set())


class Broken(Idle):
    def decide(self,scene):
        raise ValueError('test policy failure')


class Malformed(Idle):
    def decide(self,scene):
        return object()


class EvaluationTests(unittest.TestCase):
    def test_manifest_has_thirty_distinct_legal_conditions_before_games(self):
        manifest=make_manifest()
        self.assertEqual(len(manifest['conditions']),30)
        self.assertEqual(len({json.dumps(c['spawns'],sort_keys=True)
                              for c in manifest['conditions']}),30)
        validate_manifest(manifest)
        bad=deepcopy(manifest)
        bad['conditions'][-1]['spawns'][0]['x']=-100
        with self.assertRaises(ValueError):
            validate_manifest(bad)

    def test_two_swapped_games_replay_and_keep_timeout_draws(self):
        manifest=make_manifest()
        manifest['round_limit']=3/60
        manifest['conditions']=manifest['conditions'][:1]
        manifest['strategy_versions']={'hard':Idle.version,'simple':Idle.version}
        with tempfile.TemporaryDirectory() as directory:
            with patch('tank_game.evaluation.make_policy',lambda name:Idle()):
                report=run_manifest(manifest,Path(directory))
            self.assertEqual(len(report['games']),2)
            a,b=report['games']
            self.assertEqual(a['assignments'],{'tank-1':'hard','tank-2':'simple'})
            self.assertEqual(b['assignments'],{'tank-1':'simple','tank-2':'hard'})
            for game in (a,b):
                self.assertEqual(game['result'],'draw')
                self.assertEqual(game['reason'],'time_limit')
                self.assertEqual(game['invalid_actions'],0)
                replay=replay_trace(Path(directory)/game['trace'])
                self.assertEqual(replay['final_scene'],game['final_scene'])
                self.assertEqual(replay['action_digest'],game['action_digest'])

    def test_policy_failures_are_retained_as_idle_not_dropped_games(self):
        manifest=make_manifest()
        manifest['round_limit']=1/60
        manifest['conditions']=manifest['conditions'][:1]
        manifest['strategy_versions']={'hard':Broken.version,'simple':Broken.version}
        with tempfile.TemporaryDirectory() as directory:
            with patch('tank_game.evaluation.make_policy',lambda name:Broken()):
                report=run_manifest(manifest,Path(directory))
            self.assertEqual(len(report['games']),2)
            self.assertEqual(report['aggregate']['failed_decisions'],4)
            self.assertEqual(report['aggregate']['draws'],2)

    def test_host_hit_records_do_not_enter_public_agent_inputs(self):
        w=duel()
        w._bullets=(BulletState('self',122,100,-100,0,radius=2,owner_id='tank-1'),)
        for _ in range(10):
            w.step()
        self.assertEqual(len(w.hit_events),1)
        event=w.hit_events[0]
        self.assertEqual(event.tank_id,event.owner_id)
        scene=w.observe('tank-1')
        self.assertNotIn('owner_id',json.dumps(scene))
        self.assertNotIn('hit_events',scene)
        self.assertIsInstance(w.hit_events,tuple)

    def test_inline_time_budget_disables_slow_policy_until_restart(self):
        with patch('tank_game.agents.perf_counter',side_effect=[0,.3]):
            worker=InlineWorker(Idle(),timeout=.25)
            scheduler=AgentScheduler(worker)
            request=scheduler.request(World().observe('tank-1'))
        self.assertEqual(request['throttle'],0)
        self.assertEqual(scheduler.failures,1)
        self.assertTrue(worker.disabled)
        self.assertFalse(worker.submit(World().observe('tank-1')))

    def test_malformed_policy_responses_do_not_destroy_episode_evidence(self):
        manifest=make_manifest()
        manifest['round_limit']=1/60
        manifest['conditions']=manifest['conditions'][:1]
        manifest['strategy_versions']={'hard':Malformed.version,'simple':Malformed.version}
        with tempfile.TemporaryDirectory() as directory, patch(
                'tank_game.evaluation.make_policy',lambda name:Malformed()):
            report=run_manifest(manifest,Path(directory))
        self.assertEqual(len(report['games']),2)
        self.assertEqual(report['aggregate']['rejected_decisions'],4)
        self.assertEqual(report['aggregate']['invalid_actions'],0)
