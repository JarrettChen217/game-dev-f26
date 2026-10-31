"""Host scheduling and process isolation for public-observation-only policies.

Process isolation protects responsiveness, not a security sandbox. Policies are
trusted local code; only their detached scene inputs form the playing contract.
"""

from copy import deepcopy
from math import isfinite
from time import perf_counter

from tank_game.actions import validate_request
from tank_game.control_math import target_turn
from tank_game.controllers import keyboard_request


class InlineWorker:
    """Deterministic headless execution; never used by the realtime window."""

    def __init__(self, policy, *, timeout=None):
        self.policy = policy
        self.result = None
        self.timeout = timeout
        self.disabled = False
        self.last_response = None

    def submit(self, scene):
        if self.disabled:
            return False
        original = deepcopy(scene)
        start = perf_counter()
        try:
            request = self.policy.decide(deepcopy(original))
        except Exception:  # noqa: BLE001 -- contain arbitrary trusted policy failures
            request = None
        duration = perf_counter()-start
        self.last_response = request
        if self.timeout is not None and duration > self.timeout:
            self.disabled = True
            request = None
        self.result = original, request, duration
        return True

    def poll(self):
        result, self.result = self.result, None
        return result

    def discard_pending(self):
        self.result = None

    def close(self):
        self.result = None


class AgentScheduler:
    """Validate original decision identity, then wrap retained axes per tick."""

    def __init__(self, worker, *, decision_hz=10):
        if type(decision_hz) is not int or decision_hz <= 0:
            raise ValueError('decision_hz must be a positive integer')
        self.worker = worker
        self.decision_hz = decision_hz
        self.round_id = None
        self.cached = None
        self.last_accepted_tick = -1
        self.decisions = self.failures = self.rejected = 0
        self.decision_seconds = []

    def _accept(self, result, scene, interval):
        if result is None:
            return False
        original, data, duration = result
        self.decisions += 1
        self.decision_seconds.append(duration)
        if data is None:
            self.failures += 1
            self.cached = None
            return False
        age = scene['observation_tick']-original['observation_tick']
        turn_ticks = interval
        turn_target = None
        if type(data) is dict:
            data = dict(data)
            turn_ticks = data.pop('turn_ticks', interval)
            turn_target = data.pop('turn_target_deg', None)
        action = validate_request(data, source_id=scene['self_id'],
                                  round_id=scene['round_id'], tick=original['observation_tick'])
        if (action is None or type(turn_ticks) is not int or not 0 <= turn_ticks <= interval
                or (turn_target is not None and (type(turn_target) not in (int,float)
                    or not isfinite(turn_target) or not 0 <= turn_target < 360))
                or original['round_id'] != scene['round_id']
                or original['self_id'] != scene['self_id'] or not 0 <= age < interval
                or original['observation_tick'] <= self.last_accepted_tick):
            self.rejected += 1
            self.cached = None
            return False
        self.cached = action, original['observation_tick'], turn_ticks, turn_target
        self.last_accepted_tick = original['observation_tick']
        return action.fire

    def request(self, scene):
        tick = scene['observation_tick']
        hz = scene['rules']['tick_rate']
        if hz % self.decision_hz:
            raise ValueError('decision rate must divide the physics rate')
        interval = hz//self.decision_hz
        if self.round_id != scene['round_id']:
            self.round_id = scene['round_id']
            self.cached = None
            self.last_accepted_tick = -1
        idle = keyboard_request(scene, set())
        if scene['round_status'] != 'PLAYING' or not scene['self_status']['alive']:
            self.cached = None
            self.worker.poll()  # drain, never apply, old terminal results
            return idle
        fire = self._accept(self.worker.poll(), scene, interval)
        if tick % interval == 0 and self.worker.submit(scene):
            fire = self._accept(self.worker.poll(), scene, interval) or fire
        if self.cached is None or tick-self.cached[1] >= interval:
            self.cached = None
            return idle
        action, original_tick, turn_ticks, turn_target = self.cached
        turn = action.turn if tick-original_tick < turn_ticks else 0
        if turn_target is not None:
            tank=next(t for t in scene['tanks'] if t['id']==scene['self_id'])
            turn=target_turn(turn,tank['heading_deg'],turn_target,
                             scene['rules']['turn_speed_deg']/hz)
        idle.update(throttle=action.throttle, turn=turn, fire=bool(fire))
        return idle

    def pause(self, scene):
        """Invalidate pre-pause actions while preserving the worker's policy."""
        self.cached = None
        self.round_id = scene['round_id']
        self.last_accepted_tick = scene['observation_tick']
        discard = getattr(self.worker, 'discard_pending', None)
        if discard is not None:
            discard()
        self.worker.poll()

    def close(self):
        self.cached = None
        self.worker.close()


def __getattr__(name):
    """Preserve explicit legacy imports without loading native workers eagerly."""
    if name == 'ProcessWorker':
        from tank_game.process_worker import ProcessWorker
        return ProcessWorker
    raise AttributeError(name)
