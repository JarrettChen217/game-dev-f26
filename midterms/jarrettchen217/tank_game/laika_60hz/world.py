"""Public Simulator mapping of the single native source60Hz authority.

The25Hz adapter supplies action validation/lifecycle and geometry formatting.
This profile supplies its own transport, units and authoritative phase facts.
"""
import json

from tank_game.laika_60hz.bridge import ASSETS, NativeBridge
from tank_game.original_laika.world import OriginalWorld, validate_seed

PROFILE = 'laika-source-60hz-v1'


class World60(OriginalWorld):
    def __init__(self, seed=1000):
        validate_seed(seed)
        self.seed = seed
        self._bridge = NativeBridge()
        self._packet = self._bridge.call('init', seed=seed)
        self._manifest = {'wasm_sha256': None}  # replaced in the public provenance below
        self._source_manifest = json.loads((ASSETS/'manifest.json').read_text())
        self._round_id, self._tick, self._rejected = 1, 0, 0
        self._pending = None
        self._deaths = {}
        self._previous = self._packet
        self._closed = False

    @property
    def diagnostics(self):
        return dict(self._bridge.diagnostics)

    def observe(self, self_id):
        scene = super().observe(self_id)
        scene['schema_version'] = 11
        scene['rules_profile'] = PROFILE
        scene['engine_provenance'] = {'kind': 'original-source-60hz-adaptation',
                                      'sha256': self._source_manifest['library_sha256'],
                                      'target': self._source_manifest['target']}
        scene['controller_roles']['tank-2'] = 'source-laika-60hz'
        scene['rules'].update(tick_rate=60, settlement_frames=180,
                              wall_collision='source-probe-ring-5-substeps',
                              discrete_turn_snap=False)
        for bullet in scene['bullets']:
            bullet['vx'] *= 60/25
            bullet['vy'] *= 60/25
        scene['duel']['elapsed'] = self._tick/60
        scene['effects'] = [{'kind': 'explosion', 'x': x, 'y': y,
                            'progress': min(1, (self._tick-tick)/21)}
                           for x, y, tick in self._deaths.values() if self._tick-tick < 21]
        return scene

    def presentation_facts(self):
        """Host-only facts for the shared HUD; never appended to actor input.

        The pinned source freezes at end_count120. Its remaining180 live
        settlement ticks are converted using the actual60Hz profile, including
        a fresh counter after a second death. No presentation wall clock runs.
        """
        scene = self.observe('tank-1')
        rate = scene['rules']['tick_rate']
        settling = scene['round_phase'] == 'settling'
        return {'round_id': self._round_id, 'observation_tick': self._tick,
                'round_phase': scene['round_phase'], 'result': scene['duel']['result'],
                'settlement': {'remaining_seconds': max(0., (self.raw_render[13]-120)/rate) if settling else 0.,
                               'total_seconds': scene['rules']['settlement_frames']/rate},
                'source_seats': {'tank-1': 1, 'tank-2': 0},
                'survivors': [tank['id'] for tank in scene['tanks']],
                'round_scores': {'tank-1': int(self.raw_render[11]), 'tank-2': int(self.raw_render[10])}}

    def render_scene(self, alpha):
        raise RuntimeError('source60Hz presentation must render the authoritative snapshot directly')
