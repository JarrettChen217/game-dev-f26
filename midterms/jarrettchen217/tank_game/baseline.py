"""Small fixed-map smoke reproduction, not the S2.2 comparison harness."""

import hashlib
import json

from tank_game.agents import AgentScheduler, InlineWorker
from tank_game.episodes import EpisodeSpec, create_world
from tank_game.patrol import SimplePatrol
from tank_game.runner import MatchRunner


def run_baseline(*, steps=2400):
    if type(steps) is not int or steps <= 0:
        raise ValueError('steps must be a positive integer')
    world = create_world(EpisodeSpec(duel=True))
    schedulers = {key: AgentScheduler(InlineWorker(SimplePatrol()))
                  for key in ('tank-1', 'tank-2')}
    initial = world.observe('tank-1')
    digest = hashlib.sha256()
    live = projectile = restarts = invalid = 0
    results = []
    class Recorder:
        def begin_tick(self, tick, phase): pass
        def before_request(self, tid, scene): pass
        def after_request(self, tid, scene, request, *, submitted):
            if submitted:
                digest.update(json.dumps(request, sort_keys=True).encode())
        def end_tick(self): pass
    runner = MatchRunner(world, schedulers, recorder=Recorder())
    empty_runner = MatchRunner(world, {})
    try:
        for _ in range(steps):
            scene = world.observe('tank-1')
            if scene['round_status'] == 'GAME_OVER':
                results.append(scene['duel']['result'])
                invalid += world.rejected_actions
                world.restart()
                restarts += 1
                empty_runner.tick()  # Original restart frame has no controller requests.
            else:
                if scene['round_status'] == 'PLAYING':
                    live += 1
                    projectile += bool(scene['bullets'])
                runner.tick()
    finally:
        for scheduler in schedulers.values():
            scheduler.close()
    return {'policy': SimplePatrol.version, 'map': 'fixed-v1', 'steps': steps,
            'initial_tanks': initial['tanks'], 'rules': initial['rules'],
            'decision_hz': 10, 'live_steps': live, 'projectile_steps': projectile,
            'restarts': restarts, 'round_results': results,
            'invalid_actions': invalid+world.rejected_actions,
            'decisions': sum(s.decisions for s in schedulers.values()),
            'failed_decisions': sum(s.failures+s.rejected for s in schedulers.values()),
            'action_digest': digest.hexdigest(), 'final_scene': world.observe('tank-1')}
