"""User-invoked package diagnostics, independent of a display or source tree."""

import json
import os
import sys
import tempfile
from pathlib import Path
from time import monotonic, sleep

from tank_game.actions import validate_request
from tank_game.agents import AgentScheduler
from tank_game.keymap import load_keymap
from tank_game.process_worker import ProcessWorker
from tank_game.strategies import make_policy
from tank_game.tutorial_progress import load_completed, save_completed
from tank_game.world import World


def _check_workers(strategy):
    result = {'strategy': strategy, 'responses': 0, 'pids': [], 'closed': False,
              'startup_seconds': [], 'decision_seconds': []}
    for _ in range(2):
        world = World(duel=True)
        # Diagnose readiness separately in source and frozen runs alike.
        worker = ProcessWorker(make_policy(strategy), timeout=.25, startup_timeout=2)
        scheduler = AgentScheduler(worker)
        result['pids'].append(worker.process.pid)
        try:
            for _ in range(3):
                scene = world.observe('tank-2')
                if not worker.submit(scene):
                    raise RuntimeError(f'{strategy}: response request rejected')
                deadline = monotonic()+3
                response = None
                while response is None and monotonic() < deadline:
                    response = worker.poll()
                    if response is None:
                        sleep(.002)
                if response is None:
                    raise RuntimeError(f'{strategy}: response deadline exceeded')
                # Use the production host validator for policy extension fields.
                # Hold simulation time here; this is a process/engine diagnostic,
                # not a realtime match or performance evaluation.
                fire = scheduler._accept(response, scene, 6)
                if (worker.disabled or scheduler.failures or scheduler.rejected
                        or scheduler.cached is None):
                    raise RuntimeError(f'{strategy}: invalid or late response '
                                       f'(ready={worker.ready}, startup={worker.startup_seconds}, '
                                       f'response_seconds={response[2]})')
                result['decision_seconds'].append(response[2])
                action = scheduler.cached[0]
                request = {key: scene[key] for key in ('round_id', 'observation_tick')}
                request.update(tank_id='tank-2', throttle=action.throttle,
                               turn=action.turn, fire=bool(fire))
                if validate_request(request, source_id='tank-2', round_id=scene['round_id'],
                                    tick=scene['observation_tick']) is None:
                    raise RuntimeError(f'{strategy}: invalid engine request')
                world.submit_action('tank-2', request)
                for _ in range(6):
                    world.step()
                result['responses'] += 1
            result['startup_seconds'].append(worker.startup_seconds)
        finally:
            worker.close()
            if worker.process.is_alive():
                # Complete bounded cleanup even on a failed diagnostic.
                worker.process.join(timeout=2)
            if worker.process.is_alive():
                raise RuntimeError(f'{strategy}: child did not close')
    result['closed'] = True
    return result


def run_diagnostics(report_path: Path) -> int:
    """Write actual engine/process evidence; never turn failures into success."""
    data = {'schema_version': 1, 'ok': False, 'pid': os.getpid(),
            'frozen': bool(getattr(sys, 'frozen', False)), 'build': {'version': 'source'},
            'ui_imported': 'pyxel' in sys.modules, 'config': False,
            'progress': False, 'workers': [], 'error': None}
    try:
        build_file = Path(__file__).with_name('build_info.json')
        if build_file.is_file():
            data['build'] = json.loads(build_file.read_text(encoding='utf-8'))
        load_keymap(enable_next_map=True, enable_ui=True)
        data['config'] = True
        with tempfile.TemporaryDirectory(prefix='tank-progress-') as directory:
            progress = Path(directory)/'progress.json'
            if not save_completed(progress) or not load_completed(progress):
                raise RuntimeError('temporary progress roundtrip failed')
        data['progress'] = True
        data['workers'] = [_check_workers(strategy) for strategy in ('simple', 'hard')]
        data['ok'] = True
    except Exception as error:  # noqa: BLE001 -- diagnostics must preserve failure evidence
        data['error'] = f'{type(error).__name__}: {error}'
    try:
        report_path = Path(report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(data, indent=2)+'\n', encoding='utf-8')
    except OSError:
        return 1
    return 0 if data['ok'] else 1
