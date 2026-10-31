"""Isolated deterministic lessons; World remains authoritative for all physics."""

from dataclasses import dataclass
from math import ceil
from types import SimpleNamespace

from tank_game.actions import validate_request
from tank_game.controllers import keyboard_request
from tank_game.laika_60hz.play_modes import SoloPlayWorld
from tank_game.map import Rect
from tank_game.match_hud import MatchFacts, SessionScore

TUTORIAL_STEPS = 5
# Host demonstration pacing only; native firing rules retain no timed cooldown.
AMMO_DEMO_SHOT_SECONDS = .5


@dataclass(frozen=True)
class TutorialScenario:
    step_number: int
    world: SoloPlayWorld
    goal: Rect | None


def make_tutorial_scenario(step_number: int, config=None) -> TutorialScenario:
    if type(step_number) is not int or not 1 <= step_number <= TUTORIAL_STEPS:
        raise ValueError('unknown tutorial step')
    if config is not None:
        raise ValueError('Tutorial uses fixed native rules; custom GameConfig is research-only')
    world = SoloPlayWorld(1000, lesson=step_number)
    scale = world.observe('tank-1')['map']['tile_size']
    goal = (Rect(4.25*scale, .125*scale, 1.5*scale, 1.5*scale) if step_number == 1 else
            Rect(6.25*scale, .25*scale, 1.5*scale, 1.5*scale) if step_number == 2 else None)
    return TutorialScenario(step_number, world, goal)


class TutorialSession:
    def __init__(self, config=None):
        self.scenario = make_tutorial_scenario(1, config)
        self.config = SimpleNamespace(**self.scenario.world.observe('tank-1')['rules'])
        self._closed = False
        self._reset()

    @property
    def step_number(self) -> int:
        return self.scenario.step_number

    @property
    def goal_dwell_seconds(self) -> float:
        return self._goal_ticks / self.config.tick_rate

    def _reset(self):
        self.phase = 'active'
        self.round_score = SessionScore(('tank-1', 'tank-2'))
        self.error = None
        self._goal_ticks = 0
        self.shot_fired = False
        self.bounce_observed = False
        self._shot_id = None
        self._shot_ticks = 0
        self._previous_velocity = None
        self.ammo_started = False
        self.ammo_shots_fired = 0
        self.ammo_changed_slots = ()
        self._ammo_flash_ticks = 0
        self._ammo_ticks = 0
        self._ammo_birth_ticks = {}
        self._ammo_velocities = {}
        self._ammo_bounced = set()
        self._ammo_expired = set()
        self._ammo_peak = 0

    @property
    def round_facts(self) -> MatchFacts:
        """Read-only teaching HUD facts from native state, including its settlement clock."""
        world = self.scenario.world
        scene = world.observe('tank-1')
        phase = {'active': 'playing', 'settling': 'settling', 'frozen': 'finished'}[scene['round_phase']]
        alive = tuple(tank['id'] for tank in scene['tanks'] if tank['alive'])
        return MatchFacts(
            round_id=scene['round_id'], phase=phase, alive_ids=alive,
            remaining_seconds=max(0., (world.raw_render[13]-120)/self.config.tick_rate)
            if phase == 'settling' else 0.,
            total_seconds=self.config.settlement_frames/self.config.tick_rate,
            winner_id=alive[0] if phase == 'finished' and len(alive) == 1 else None)

    @property
    def ammo_flash_seconds(self) -> float:
        return self._ammo_flash_ticks / self.config.tick_rate

    @property
    def ammo_stage(self) -> str:
        if self.phase in ('complete', 'error'):
            return self.phase
        if not self.ammo_started:
            return 'ready'
        if self.ammo_shots_fired < self.config.max_bullets:
            return 'loading'
        count = self.scenario.world.observe('tank-1')['self_status']['active_bullets']
        return 'full' if count == self.config.max_bullets else 'recharging'

    def tick(self, request: dict | None) -> None:
        if self._closed or self.phase != 'active':
            return
        world = self.scenario.world
        scene = world.observe('tank-1')
        action = validate_request(request, source_id='tank-1', round_id=scene['round_id'],
                                  tick=scene['observation_tick'])
        if self.step_number == 5:
            self._tick_ammo(action, scene)
            return
        if self.step_number >= 3:
            self._tick_demo(request, action, scene)
            return
        if action is not None:
            # Validate before masking so malformed/stale requests stay invalid.
            world.submit_action('tank-1', {**request, 'fire': False})
        world.step()
        self._update_goal(world.observe('tank-1'))

    def _tick_demo(self, request, action, scene):
        world = self.scenario.world
        if not self.shot_fired and (action is None or not action.fire):
            return  # Reading the instructions never runs an episode clock.
        if (action is not None and scene['round_status'] == 'PLAYING'
                and scene['self_status']['alive']):
            world.submit_action('tank-1', {**request, 'throttle': 0, 'turn': 0,
                                          'fire': action.fire and not self.shot_fired})
        world.step()
        current = world.observe('tank-1')
        if not self.shot_fired:
            spawned = current['bullets']
            hits = [event for event in world.hit_events if event.owner_id == 'tank-1']
            if spawned or hits:
                self.shot_fired = True
                self._shot_id = spawned[0]['id'] if spawned else hits[0].bullet_id
        if not self.shot_fired:
            return
        self._shot_ticks += 1
        bullet = next((b for b in current['bullets'] if b['id'] == self._shot_id), None)
        if bullet is not None:
            velocity = (bullet['vx'], bullet['vy'])
            if (self._previous_velocity is not None
                    and sum(a*b for a, b in zip(velocity, self._previous_velocity)) < 0):
                self.bounce_observed = True
            self._previous_velocity = velocity
        self.bounce_observed |= any(e.has_bounced for e in world.hit_events)
        if current['round_phase'] in ('settling', 'frozen'):
            expected_tank = 'tank-2' if self.step_number == 3 else 'tank-1'
            hit = any(event.tank_id == expected_tank and event.bullet_id == self._shot_id
                      and event.owner_id == 'tank-1' for event in world.hit_events)
            expected = (hit and current['self_status']['alive'] if self.step_number == 3
                        else hit and self.bounce_observed and not current['self_status']['alive'])
            if not expected:
                self.phase, self.error = 'error', 'unexpected demonstration outcome'
            elif current['round_status'] == 'GAME_OVER' and not current['effects']:
                self.phase = 'success'
                self.round_score.record(self.round_facts)
        limit = self.config.bullet_lifetime + self.config.settlement_frames/self.config.tick_rate + 1
        if self.phase == 'active' and self._shot_ticks >= ceil(limit * self.config.tick_rate):
            self.phase, self.error = 'error', 'demonstration watchdog expired'

    def _tick_ammo(self, action, scene):
        if not self.ammo_started:
            if action is None or not action.fire:
                return
            self.ammo_started = True
        world = self.scenario.world
        self._ammo_ticks += 1
        self._ammo_flash_ticks = max(0, self._ammo_flash_ticks - 1)
        capacity = self.config.max_bullets
        gap = ceil(AMMO_DEMO_SHOT_SECONDS * self.config.tick_rate)
        fire = (self.ammo_shots_fired < capacity and scene['self_status']['can_fire']
                and (self._ammo_ticks - 1) % gap == 0)
        # The host schedules a bounded burst through the normal action ingress.
        # Space out the demo shots so their sprites separate. Native Game still owns
        # release/repress, capacity, flight and expiry; this is not a gameplay cooldown.
        world.submit_action('tank-1', keyboard_request(scene, set(), fire_pressed=fire))
        world.step()
        current = world.observe('tank-1')
        if not current['self_status']['alive'] or world.hit_events:
            self.phase, self.error = 'error', 'unexpected ammo demonstration hit'
            return
        if current['round_status'] != 'PLAYING':
            self.phase, self.error = 'error', 'unexpected ammo demonstration ending'
            return
        previous_ids = {bullet['id'] for bullet in scene['bullets']}
        if fire and not any(bullet['id'] not in previous_ids for bullet in current['bullets']):
            # A blocked muzzle or birth-tick expiry cannot demonstrate a slot.
            # Stop here rather than retrying an unobservable shot indefinitely.
            self.phase, self.error = 'error', 'ammo shot was not observable'
            return
        alive_ids = set()
        for bullet in current['bullets']:
            bullet_id = bullet['id']
            alive_ids.add(bullet_id)
            if bullet_id not in self._ammo_birth_ticks:
                self._ammo_birth_ticks[bullet_id] = self._ammo_ticks
                self.ammo_shots_fired += 1
            velocity = bullet['vx'], bullet['vy']
            if (bullet_id in self._ammo_velocities
                    and velocity != self._ammo_velocities[bullet_id]):
                self._ammo_bounced.add(bullet_id)
            self._ammo_velocities[bullet_id] = velocity
        for bullet_id, birth_tick in self._ammo_birth_ticks.items():
            if bullet_id in alive_ids or bullet_id in self._ammo_expired:
                continue
            # Native birth frames do not move/age the projectile.
            age = (self._ammo_ticks - birth_tick) / self.config.tick_rate
            native_expired = {f'bullet-{bid}' for bid in world.native_facts['expired']}
            if age + 1e-9 < self.config.bullet_lifetime or bullet_id not in native_expired:
                self.phase, self.error = 'error', 'ammo bullet vanished before expiry'
                return
            self._ammo_expired.add(bullet_id)
        count = current['self_status']['active_bullets']
        self._ammo_peak = max(self._ammo_peak, count)
        previous_free = capacity - scene['self_status']['active_bullets']
        free = capacity - count
        if previous_free != free:
            self.ammo_changed_slots = tuple(range(min(free, previous_free),
                                                  max(free, previous_free)))
            self._ammo_flash_ticks = ceil(.6 * self.config.tick_rate)
        self.shot_fired = self.ammo_shots_fired > 0
        if self.ammo_shots_fired == capacity and len(self._ammo_expired) == capacity:
            if self._ammo_peak == capacity and len(self._ammo_bounced) == capacity:
                self.phase = 'complete'
            else:
                self.phase, self.error = 'error', 'ammo fill or bounce was not observed'
        limit = ((capacity - 1) * gap/self.config.tick_rate
                 + self.config.bullet_lifetime + 1)
        if self.phase == 'active' and self._ammo_ticks >= ceil(limit*self.config.tick_rate):
            self.phase, self.error = 'error', 'ammo demonstration watchdog expired'

    def _update_goal(self, scene):
        goal = self.scenario.goal
        tank = next((tank for tank in scene['tanks'] if tank['id'] == 'tank-1'), None)
        contained = False
        if goal is not None and tank is not None and scene['self_status']['alive']:
            # Quantized public coordinates must not admit an actually outside tank.
            radius = tank['radius'] + scene['observation_precision']['position'] / 2
            contained = (goal.x + radius <= tank['x'] <= goal.x + goal.width - radius
                         and goal.y + radius <= tank['y'] <= goal.y + goal.height - radius)
        self._goal_ticks = self._goal_ticks + 1 if contained else 0
        if self._goal_ticks >= ceil(.25 * self.config.tick_rate):
            self.phase = 'success'

    def _replace(self, step_number):
        if self._closed:
            return False
        try:
            candidate = make_tutorial_scenario(step_number)
        except (ValueError, OSError, RuntimeError) as error:
            self.phase, self.error = 'error', str(error)
            return False
        old = self.scenario.world
        self.scenario = candidate
        old.close()
        self._reset()
        return True

    def advance(self) -> bool:
        return self.phase == 'success' and self._replace(self.step_number + 1)

    def retry(self) -> bool:
        return self._replace(self.step_number)

    def close(self):
        if not self._closed:
            self._closed = True
            self.scenario.world.close()
