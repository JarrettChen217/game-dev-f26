"""Single-player/lesson host projection of the same native Game; no integrator."""
from dataclasses import dataclass

from tank_game.laika_60hz.mac_play import HybridPlayWorld


@dataclass(frozen=True)
class PlayHit:
    bullet_id: str
    owner_id: str
    tank_id: str
    elapsed: float
    has_bounced: bool


class SoloPlayWorld(HybridPlayWorld):
    def __init__(self, seed=1000, *, lesson=0):
        if type(lesson) is not int or not 0 <= lesson <= 5:
            raise ValueError('choose practice0 or lesson1..5')
        self.lesson = lesson
        self._hits = []
        super().__init__(seed, strategy='simple', fixture=lesson+1)
        self.presentation_seats = (('tank-1','YOU'),('tank-2','TARGET'))

    @property
    def native_facts(self):
        return self._bridge.facts

    @property
    def hit_events(self):
        return tuple(self._hits)

    def observe(self, self_id):
        scene = super().observe(self_id)
        if self.lesson != 3:
            if self_id != 'tank-1':
                raise ValueError('single-player world has only tank-1')
            scene.pop('duel', None)
            scene['tanks'] = [t for t in scene['tanks'] if t['id']=='tank-1']
            scene['all_tanks'] = [t for t in scene['all_tanks'] if t['id']=='tank-1']
        scene['controller_roles'] = {'tank-1':'human'} | ({'tank-2':'stationary-target'} if self.lesson==3 else {})
        scene['presentation_heading'] = f'Tutorial {self.lesson}/5 /60Hz' if self.lesson else 'Single tank practice /60Hz'
        scene['presentation_mode'] = 'tutorial' if self.lesson else 'practice'
        if self.raw_render[13] < 0 and not self.raw_render[14]:
            scene['round_phase'] = 'active'
        facts = self.native_facts
        scene['self_status']['trigger_released'] = facts['trigger_released']
        scene['self_status']['can_fire'] &= facts['trigger_released']
        scene['bullets'] = [{'id':f'bullet-{int(b[0])}', 'owner_id':'tank-1' if b[1]==1 else 'tank-2',
                             'x':b[2], 'y':b[3], 'vx':b[4]*7*60, 'vy':b[5]*7*60,
                             'radius':0., 'visual_radius':max(2.,2.5*scene['map']['tile_size']/50),
                             'remaining_lifetime':b[6]/60, 'has_bounced':bool(b[7])}
                            for b in facts['bullets']]
        scene['bullet_identity'] = 'native-stable-id'
        return scene

    def step(self):
        before = self._tick
        super().step()
        if self._tick != before:
            for bid,owner,victim,bounced in self.native_facts['hits']:
                self._hits.append(PlayHit(f'bullet-{int(bid)}', 'tank-1' if owner==1 else 'tank-2',
                                         'tank-1' if victim==1 else 'tank-2', self._tick/60, bool(bounced)))

    def restart(self, **kwargs):
        changed = super().restart(**kwargs)
        if changed:
            self._hits.clear()
        return changed
