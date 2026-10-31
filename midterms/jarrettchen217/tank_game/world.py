"""Simulation-owned driving state and detached public scene snapshots."""

from dataclasses import asdict, dataclass, replace
from math import cos, floor, isfinite, radians, sin

from tank_game.actions import Action, validate_request
from tank_game.config import GameConfig
from tank_game.duel import legal_spawns, stop_pair
from tank_game.entities import BulletState, TankState
from tank_game.hull import PROFILE, first_body_hit, move_rectangle
from tank_game.map import GameMap, fixed_map
from tank_game.paths import Segment, first_hit, position
from tank_game.physics import (
    CONTACT_GAP,
    circle_clear,
    first_wall_contact,
    move_circle,
    ricochet_circle,
)


def quantize(value: float, subdivisions: int = 8) -> float:
    """Round to a public subunit; exact halves round toward positive infinity."""
    return floor(value * subdivisions + 0.5) / subdivisions


@dataclass(frozen=True)
class HitEvent:
    """Immutable host diagnostics, deliberately excluded from public observations."""

    tank_id: str
    bullet_id: str
    owner_id: str
    elapsed: float


class World:
    def __init__(self, game_map: GameMap | None = None, config: GameConfig | None = None,
                 *, duel: bool = False, spawns=None, round_limit: float = 120, collision_profile='circle'):
        if collision_profile not in ('circle','rectangle'):
            raise ValueError('unknown collision profile')
        self._collision_profile = collision_profile
        self._wall_contacts = {}
        self._wall_blocked = {}
        self._config = config if config is not None else GameConfig()
        self._map = game_map if game_map is not None else fixed_map()
        self._map.validate(self._config.tank_radius)
        if type(duel) is not bool:
            raise ValueError('duel must be a boolean')
        if type(round_limit) not in (int, float) or not isfinite(round_limit) or round_limit <= 0:
            raise ValueError('round_limit must be finite and positive')
        if not duel and spawns is not None:
            raise ValueError('Multiple spawns require duel mode')
        self._duel = duel
        self._spawns = (legal_spawns(self._map, self._config.tank_radius, spawns)
                        if duel else (self._map.spawn,))
        self._round_limit = round_limit
        self._elapsed = 0.0
        self._result = None
        self._tanks = {f'tank-{i+1}': TankState(f'tank-{i+1}', s.x, s.y, s.heading_deg,
                                              radius=self._config.tank_radius)
                       for i, s in enumerate(self._spawns)}
        self._bullets: tuple[BulletState, ...] = ()
        self._round_id = 1
        self._tick = 0
        self._round_status = 'PLAYING'
        self._pending: dict[str, Action] = {}
        self._rejected_actions = 0
        self._collision_limit_hits = 0
        self._projectile_limit_hits = 0
        self._next_bullet_id = 1
        self._death_positions = ()
        self._dying_remaining = 0.0
        self._hit_events = ()

    @property
    def hit_events(self) -> tuple[HitEvent, ...]:
        return self._hit_events

    @property
    def collision_limit_hits(self) -> int:
        """Host diagnostics only; capped motion is never allowed to cross a wall."""
        return self._collision_limit_hits

    @property
    def projectile_limit_hits(self) -> int:
        """Host-only count of conservatively stopped projectile steps."""
        return self._projectile_limit_hits

    @property
    def rejected_actions(self) -> int:
        """Diagnostics for the host/test harness; not serialized for controllers."""
        return self._rejected_actions

    def observe(self, self_id: str) -> dict:
        if type(self_id) is not str or self_id not in self._tanks:
            raise ValueError('Unknown controlled tank')
        tank = self._tanks[self_id]
        active = sum(bullet.owner_id == self_id for bullet in self._bullets)
        scene = {
            'schema_version': 6 if self._duel else 5, 'round_id': self._round_id,
            'observation_precision': {'position': .125, 'heading_deg': .25, 'velocity': .125},
            'observation_tick': self._tick, 'self_id': self_id,
            'map': {'width': self._map.width, 'height': self._map.height,
                    'tile_size': self._map.tile_size,
                    'columns': self._map.columns, 'rows': self._map.rows,
                    'wall_thickness': self._map.wall_thickness,
                    'walls': [asdict(wall) for wall in self._map.walls]},
            'rules': asdict(self._config),
            'tanks': [{'id': t.id, 'x': quantize(t.x), 'y': quantize(t.y),
                       'heading_deg': quantize(t.heading_deg, 4) % 360, 'radius': t.radius}
                      for t in sorted(self._tanks.values(), key=lambda t: t.id) if t.alive],
            'bullets': [{'id': b.id, 'x': quantize(b.x), 'y': quantize(b.y),
                         'vx': quantize(b.vx), 'vy': quantize(b.vy), 'radius': b.radius,
                         'remaining_lifetime': max(0, self._config.bullet_lifetime-b.age)}
                        for b in self._bullets],
            'self_status': {'alive': tank.alive, 'active_bullets': active,
                            'cooldown_remaining': tank.cooldown_remaining,
                            'can_fire': tank.alive and self._round_status == 'PLAYING'
                            and tank.cooldown_remaining == 0
                            and active < self._config.max_bullets},
            'round_status': self._round_status,
            'effects': self._effects(),
        }
        if self._collision_profile=='rectangle':
            scene['schema_version'] = 8 if self._duel else 7
            scene['collision_profile'] = dict(PROFILE)
            scene['self_status']['wall_contact'] = self._wall_contacts.get(self_id,False)
            scene['self_status']['wall_blocked'] = self._wall_blocked.get(self_id,False)
        if self._duel:
            scene['duel'] = {'elapsed': self._elapsed, 'limit': self._round_limit,
                             'result': self._result}
        return scene

    def submit_action(self, source_id: str, data: object) -> Action:
        action = validate_request(data, source_id=source_id,
                                  round_id=self._round_id, tick=self._tick)
        if (type(source_id) is not str or source_id not in self._tanks
                or not self._tanks[source_id].alive or self._round_status != 'PLAYING'
                or source_id in self._pending or action is None):
            self._rejected_actions += 1
            return Action()
        self._pending[source_id] = action
        return action

    def _effects(self) -> list[dict]:
        if self._round_status != 'DYING':
            return []
        return [{'kind': 'explosion', 'x': quantize(x), 'y': quantize(y),
                 'progress': 1 - self._dying_remaining / self._config.explosion_duration}
                for x, y in self._death_positions]

    def restart(self, *, game_map: GameMap | None = None, spawns=None, allow_active=False) -> bool:
        """Host-only replacement; active-round abandonment requires explicit opt-in."""
        if self._round_status != 'GAME_OVER' and not allow_active:
            return False
        next_round = self._round_id + 1
        maze = self._map if game_map is None else game_map
        selected = self._spawns if game_map is None and spawns is None else spawns
        replacement = World(maze, self._config, duel=self._duel,
                            spawns=selected if self._duel else None,
                            round_limit=self._round_limit,collision_profile=self._collision_profile)
        replacement._round_id = next_round
        self.__dict__.update(replacement.__dict__)
        return True

    def step(self) -> None:
        """State machine: only PLAYING advances physics and accepts actions.

        Existing bullets share the tank's timed sweep. Surviving tanks fire
        from the resulting pose; new bullets get S1.3's dt of flight against
        that stationary pose, never against the tank's earlier trajectory.
        """
        dt = 1 / self._config.tick_rate
        if self._round_status == 'DYING':
            self._dying_remaining = max(0, self._dying_remaining - dt)
            if self._dying_remaining <= dt * 1e-10:
                self._dying_remaining = 0
                self._round_status = 'GAME_OVER'
        elif self._round_status == 'PLAYING':
            if self._duel:
                dt = min(dt, self._round_limit-self._elapsed)
            paths = {}
            active = {tank_id: sum(b.owner_id == tank_id for b in self._bullets)
                      for tank_id in self._tanks}
            for tank_id, tank in self._tanks.items():
                if not tank.alive:
                    continue
                action = self._pending.get(tank_id, Action())
                heading = (tank.heading_deg + action.turn * self._config.turn_speed_deg * dt) % 360
                speed = (self._config.forward_speed if action.throttle > 0
                         else self._config.reverse_speed) * action.throttle
                angle = radians(heading)
                if self._collision_profile=='rectangle':
                    intended=heading
                    motion,heading=move_rectangle(tank,action.turn*self._config.turn_speed_deg*dt,
                                                   speed*dt,self._map.walls,dt)
                    self._wall_contacts[tank_id]=(abs((heading-intended+180)%360-180)>1e-8
                        or abs(motion.x-tank.x-speed*dt*cos(radians(heading)))>1e-6
                        or abs(motion.y-tank.y-speed*dt*sin(radians(heading)))>1e-6)
                    self._wall_blocked[tank_id]=bool(self._wall_contacts[tank_id] and (
                        (speed and abs(motion.x-tank.x)+abs(motion.y-tank.y)<1e-7) or
                        (action.turn and abs((heading-tank.heading_deg+180)%360-180)<1e-7)))
                else:
                    motion = move_circle(tank.x, tank.y, tank.radius,
                                         speed * dt * cos(angle), speed * dt * sin(angle),
                                         self._map.walls, duration=dt)
                self._collision_limit_hits += motion.exhausted
                paths[tank_id] = motion.path
                self._tanks[tank_id] = replace(tank, x=motion.x, y=motion.y, heading_deg=heading)
            paths = stop_pair(paths, self._tanks, dt)
            for tank_id, path in paths.items():
                x, y = position(path, dt)
                self._tanks[tank_id] = replace(self._tanks[tank_id], x=x, y=y)
            hit_time = self._advance_bullets(dt, paths)
            if self._round_status == 'PLAYING':
                existing_ids = {b.id for b in self._bullets}
                for tank_id, tank in self._tanks.items():
                    if not tank.alive:
                        continue
                    action = self._pending.get(tank_id, Action())
                    if action.fire:
                        tank = self._try_fire(tank, active[tank_id])
                    cooldown = tank.cooldown_remaining - dt
                    self._tanks[tank_id] = replace(
                        tank, cooldown_remaining=0 if cooldown <= dt * 1e-10 else cooldown)
                newborn = tuple(b for b in self._bullets if b.id not in existing_ids)
                static = {t.id: (Segment(0, dt, t.x, t.y, t.x, t.y),)
                          for t in self._tanks.values() if t.alive}
                hit_time = self._advance_bullets(dt, static, newborn)
            self._elapsed += dt if hit_time is None else hit_time
            if (self._duel and self._round_status == 'PLAYING'
                    and self._round_limit-self._elapsed <= dt*1e-9):
                self._elapsed = self._round_limit
                self._result = 'draw'
                self._round_status = 'GAME_OVER'
            self._tick += 1
        self._pending.clear()

    def _try_fire(self, tank: TankState, active: int) -> TankState:
        """Refused requests are discarded without reserving ammo or cooldown."""
        if tank.cooldown_remaining > 0:
            return tank
        if active >= self._config.max_bullets:
            return tank
        angle = radians(tank.heading_deg)
        ux, uy = cos(angle), sin(angle)
        radius = self._config.bullet_radius
        front_x, front_y = tank.x + tank.radius * ux, tank.y + tank.radius * uy
        distance = tank.radius + radius + 2 * CONTACT_GAP
        x, y = tank.x + distance * ux, tank.y + distance * uy
        walls = self._map.walls
        if (not circle_clear(front_x, front_y, radius, walls)
                or not circle_clear(x, y, radius, walls)
                or first_wall_contact(front_x, front_y, radius,
                                      x - front_x, y - front_y, walls) is not None):
            return tank
        bullet = BulletState(f'bullet-{self._next_bullet_id}', x, y,
                             self._config.bullet_speed * ux, self._config.bullet_speed * uy,
                             radius=radius, owner_id=tank.id)
        self._next_bullet_id += 1
        self._bullets += (bullet,)
        return replace(tank, cooldown_remaining=self._config.fire_interval)

    def _advance_bullets(self, dt: float, tank_paths: dict,
                         bullets: tuple[BulletState, ...] | None = None) -> float | None:
        bullets = self._bullets if bullets is None else bullets
        lifetime = self._config.bullet_lifetime
        tolerance = max(lifetime, dt) * 1e-12
        flights, hits = {}, []
        for bullet in bullets:
            remaining = lifetime - bullet.age
            if remaining <= tolerance:
                continue
            elapsed = min(dt, remaining)
            motion = ricochet_circle(bullet.x, bullet.y, bullet.radius,
                                     bullet.vx, bullet.vy, elapsed, self._map.walls)
            flights[bullet.id] = (motion, elapsed)
            for tank_id, path in tank_paths.items():
                tank=self._tanks[tank_id]
                contact = (first_body_hit(motion.path,path,tank.radius,tank.heading_deg,bullet.radius)
                           if self._collision_profile=='rectangle' else
                           first_hit(motion.path,path,bullet.radius+tank.radius))
                # Lifetime is half-open: expired bullets cannot damage at expiry.
                if contact is not None and contact < remaining - tolerance:
                    hits.append((contact, bullet.id, tank_id))
        death_time = min((hit[0] for hit in hits), default=None)
        impacting = {bullet_id for time, bullet_id, _ in hits
                     if death_time is not None and abs(time - death_time) <= 1e-10}
        selected = {b.id for b in bullets}
        survivors = [b for b in self._bullets if b.id not in selected]
        for bullet in bullets:
            if bullet.id not in flights or bullet.id in impacting:
                continue
            motion, elapsed = flights[bullet.id]
            if death_time is not None and death_time < elapsed:
                elapsed = death_time
                motion = ricochet_circle(bullet.x, bullet.y, bullet.radius,
                                         bullet.vx, bullet.vy, elapsed, self._map.walls)
            self._projectile_limit_hits += motion.exhausted
            age = bullet.age + elapsed
            if lifetime - age > tolerance:
                survivors.append(replace(bullet, x=motion.x, y=motion.y,
                                         vx=motion.vx, vy=motion.vy, age=age))
        self._bullets = tuple(survivors)
        if death_time is not None:
            owners = {b.id: b.owner_id for b in bullets}
            self._hit_events += tuple(HitEvent(tank_id, bullet_id, owners[bullet_id],
                                              self._elapsed+time)
                                     for time, bullet_id, tank_id in sorted(hits)
                                     if abs(time-death_time) <= 1e-10)
            killed = {tank_id for time, _, tank_id in hits if abs(time-death_time) <= 1e-10}
            effects = []
            for tank_id, path in tank_paths.items():
                x, y = position(path, death_time)
                self._tanks[tank_id] = replace(self._tanks[tank_id], x=x, y=y,
                                              alive=tank_id not in killed)
                if tank_id in killed:
                    effects.append((tank_id, x, y))
            self._death_positions = tuple((x, y) for _, x, y in sorted(effects))
            if self._duel:
                alive = sorted(t.id for t in self._tanks.values() if t.alive)
                self._result = alive[0] if len(alive) == 1 else 'draw'
            self._round_status = 'DYING'
            self._dying_remaining = self._config.explosion_duration
        return death_time
