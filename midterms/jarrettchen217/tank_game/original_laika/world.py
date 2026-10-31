"""Simulator interface for the original engine as the sole state authority.

No Python policy or native tank/projectile integrator is run in this profile.
The cached snapshots are observations of the WASM state, never a second World.
"""
import json
from copy import deepcopy
from math import cos, hypot, radians, sin

from tank_game.actions import Action, validate_request
from tank_game.original_laika.bridge import ASSETS, EngineBridge

PROFILE = 'laika-original-v1'
ROLES = {'tank-1': 'external', 'tank-2': 'original-laika'}


def validate_seed(seed):
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError('original Laika seed must be an integer in0..4294967295')


class OriginalWorld:
    def __init__(self, seed=1000, *, node_command=None):
        validate_seed(seed)
        self.seed = seed
        self._bridge = EngineBridge(node_command=node_command)
        try:
            self._packet = self._bridge.call('init', seed=seed)
        except Exception:
            self._bridge.close()
            raise
        self._manifest = json.loads((ASSETS/'manifest.json').read_text())
        self._round_id, self._tick, self._rejected = 1, 0, 0
        self._pending = None
        self._deaths = {}
        self._previous = self._packet
        self._closed = False

    @property
    def process(self):
        return self._bridge.process

    @property
    def raw_render(self):
        """Original float32 render export, retained for host parity diagnostics."""
        return tuple(self._packet['render'])

    @property
    def rejected_actions(self):
        return self._rejected

    @property
    def hit_events(self):
        # Original render ABI has no projectile/victim identity event stream.
        return ()

    @property
    def collision_limit_hits(self):
        return 0  # No native capped integrator is called.

    @property
    def projectile_limit_hits(self):
        return 0

    def _tanks(self, packet=None):
        raw = (self._packet if packet is None else packet)['render']
        offset = 138+int(raw[5])*4
        result = []
        for identity, seat in (('tank-1', 1), ('tank-2', 0)):
            row = raw[offset+seat*6:offset+seat*6+6]
            result.append({'id': identity, 'x': row[0], 'y': row[1],
                           'heading_deg': (row[2]-90) % 360, 'alive': row[3] > .5,
                           'radius': 55*row[5], 'display_scale': row[5]})
        return result

    def observe(self, self_id):
        if type(self_id) is not str or self_id not in ROLES:
            raise ValueError('Unknown controlled tank')
        raw, status = self._packet['render'], self._packet['status']
        columns, rows, scale, half = int(raw[0]), int(raw[1]), raw[2], raw[3]
        walls = []
        for index in range(int(raw[5])):
            x1, y1, x2, y2 = raw[138+index*4:142+index*4]
            walls.append({'x': min(x1,x2)-half, 'y': min(y1,y2)-half,
                          'width': abs(x2-x1)+2*half, 'height': abs(y2-y1)+2*half})
        tanks = self._tanks()
        own = tanks[0 if self_id == 'tank-1' else 1]
        facts = status[:12] if self_id == 'tank-1' else status[12:]
        capacity = 5
        active = capacity-round(facts[7]*capacity)
        frozen = raw[14] > .5
        result = None
        if frozen:
            survivors = [t['id'] for t in tanks if t['alive']]
            result = survivors[0] if len(survivors) == 1 else 'draw'
        bullets = []
        offset = 138+int(raw[5])*4+int(raw[6])*6
        angle = radians(tanks[0]['heading_deg'])
        for index in range(int(raw[7])):
            meta = self._packet['bullets'][index*10:index*10+10]
            ahead, lateral = meta[2]*.5*scale*25*7, meta[3]*.5*scale*25*7
            bullets.append({'id': f'original-slot-{index}',
                            'x': raw[offset+index*2], 'y': raw[offset+index*2+1],
                            'vx': ahead*cos(angle)-lateral*sin(angle),
                            'vy': ahead*sin(angle)+lateral*cos(angle),
                            'radius': 0., 'visual_radius': max(2.,2.5*scale/50),
                            'remaining_lifetime': meta[6]*10,
                            'has_bounced': meta[5] > .5,
                            'owner_id': 'tank-1' if meta[4] > .5 else 'tank-2'})
        rules = {'tick_rate': 25, 'forward_speed': 2*scale,
                 'reverse_speed': 1.25*scale, 'turn_speed_deg': 250.,
                 'bullet_speed': 2.25*scale, 'bullet_lifetime': 10.,
                 'bullet_radius': 0., 'fire_interval': 0., 'max_bullets': capacity,
                 'tank_radius': 55*.0055*scale, 'explosion_duration': .35,
                 'bullet_collision': 'point', 'tank_collision': 'hull-and-barrel-union',
                 'wall_collision': 'original-probe-ring-5-substeps',
                 'body_pair_collision': 'original-no-body-separation',
                 'projectile_substeps': 7, 'damage_sampling': 'end-of-frame',
                 'new_bullet_motion': 'next-tick', 'settlement_frames': 75}
        return {'schema_version': 10, 'rules_profile': PROFILE,
                'engine_provenance': {'kind': 'unchanged-original-wasm',
                                      'sha256': self._manifest['wasm_sha256']},
                'round_id': self._round_id, 'observation_tick': self._tick, 'self_id': self_id,
                'observation_precision': {'position': .0001, 'heading_deg': .0001,
                                          'velocity': .0001},
                'map': {'columns': columns, 'rows': rows, 'tile_size': scale,
                        'width': columns*scale, 'height': rows*scale,
                        'wall_thickness': half*2, 'walls': walls},
                'rules': rules, 'controller_roles': dict(ROLES),
                'all_tanks': tanks, 'tanks': [deepcopy(t) for t in tanks if t['alive']],
                'bullets': bullets, 'bullet_identity': 'original-render-slot-not-stable-id',
                'self_status': {'alive': own['alive'], 'active_bullets': active,
                                'can_fire': own['alive'] and not frozen and facts[8] > .5,
                                'cooldown_remaining': 0., 'wall_contact': facts[10] > .5,
                                'wall_sliding': facts[11] > .5},
                # Original source keeps survivors controllable during settlement.
                'round_status': 'GAME_OVER' if frozen else 'PLAYING',
                'round_phase': 'frozen' if frozen else 'settling' if raw[12] < 2 else 'active',
                'duel': {'elapsed': self._tick/25, 'limit': None, 'result': result},
                'effects': [{'kind': 'explosion', 'x': x, 'y': y,
                             'progress': min(1,(self._tick-tick)/9)}
                            for x,y,tick in self._deaths.values() if self._tick-tick < 9]}

    def submit_action(self, source_id, data):
        action = validate_request(data, source_id=source_id, round_id=self._round_id, tick=self._tick)
        if (self._closed or source_id != 'tank-1' or self._pending is not None or action is None
                or not self.observe('tank-1')['self_status']['alive'] or self.raw_render[14]):
            self._rejected += 1
            return Action()
        self._pending = action
        return action

    def render_scene(self, alpha):
        """Source-style display interpolation; authoritative observation stays unchanged."""
        scene = self.observe('tank-1')
        alpha = min(1,max(0,alpha))
        previous = {tank['id']: tank for tank in self._tanks(self._previous)}
        for tank in scene['tanks']:
            old = previous[tank['id']]
            tank['x'] = old['x']+(tank['x']-old['x'])*alpha
            tank['y'] = old['y']+(tank['y']-old['y'])*alpha
            delta = (tank['heading_deg']-old['heading_deg']+180) % 360-180
            tank['heading_deg'] = (old['heading_deg']+delta*alpha) % 360
        raw = self._previous['render']
        start = 138+int(raw[5])*4+int(raw[6])*6
        maximum = scene['rules']['bullet_speed']/25*1.5
        for index,bullet in enumerate(scene['bullets']):
            if index >= int(raw[7]):
                continue
            x,y = raw[start+index*2:start+index*2+2]
            if hypot(bullet['x']-x,bullet['y']-y) <= maximum:
                bullet['x'],bullet['y'] = x+(bullet['x']-x)*alpha,y+(bullet['y']-y)*alpha
        return scene

    def step(self):
        if self._closed:
            raise RuntimeError('Original World is closed')
        if not self.raw_render[14]:
            action = self._pending or Action()
            old = self._tanks()
            packet = self._bridge.call('step', action=[action.throttle,action.turn,action.fire])
            self._previous, self._packet = self._packet, packet
            self._tick += 1
            for before,after in zip(old,self._tanks(),strict=True):
                if before['alive'] and not after['alive']:
                    self._deaths[before['id']] = after['x'],after['y'],self._tick
        self._pending = None

    def restart(self, *, seed=None, game_map=None, spawns=None, allow_active=False):
        if game_map is not None or spawns is not None:
            raise ValueError('Original rules use original seeded mazes/spawns; select native for custom maps')
        if self._closed:
            return False
        if not self.raw_render[14] and not allow_active:
            return False
        selected = self.seed if seed is None else seed
        validate_seed(selected)
        packet = self._bridge.call('init', seed=selected)
        self.seed, self._packet, self._previous = selected,packet,packet
        self._round_id += 1
        self._tick, self._pending, self._deaths = 0,None,{}
        return True

    def close(self):
        if not self._closed:
            self._bridge.close()
            self._closed = True
