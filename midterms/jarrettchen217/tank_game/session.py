"""Host-owned game sessions, separate from competitive actions."""
from random import SystemRandom

from tank_game.controllers import BufferedController
from tank_game.episodes import EpisodeSpec, create_world
from tank_game.random_rounds import RandomRoundSession
from tank_game.runner import MatchRunner
from tank_game.runtime_factories import create_desktop_scheduler


def _close_all(controllers, *, excluding=()):
    seen = set(excluding)
    for controller in controllers.values():
        if id(controller) not in seen:
            seen.add(id(controller))
            controller.close()


class GameSession:
    def __init__(self, selection, *, seed=None, scheduler_factory=None,
                 controller_factories=None, source60=True):
        if scheduler_factory is not None and controller_factories is not None:
            raise ValueError('choose controller_factories or scheduler_factory')
        duel, self.strategy, random_map = selection.effective()
        self.random_session = None
        self.scheduler = None
        self.controllers = {}
        self._factory = scheduler_factory
        self._closed = False
        self._source60 = source60
        self._random_requested = random_map
        if self._source60:
            try:
                from tank_game.laika_60hz.mac_play import HybridPlaySession
                chosen = (SystemRandom().randrange(2**32) if random_map else 1000) if seed is None else seed
                self.random_session = HybridPlaySession(chosen, random_map=random_map, strategy=self.strategy, practice=not duel)
            except ImportError as error:
                raise RuntimeError('Unified60Hz requires the configured Mac play environment') from error
            self.world = self.random_session.world
        elif random_map:
            seed = SystemRandom().randrange(2**32) if seed is None else seed
            self.random_session = RandomRoundSession(seed)
            self.world = self.random_session.world
        else:
            self.world = create_world(EpisodeSpec(duel=duel))
        if controller_factories is None:
            self._controller_factories = {'tank-1': BufferedController}
            if duel and (not self._source60 or self.strategy in ('simple', 'hard')):
                self._controller_factories['tank-2'] = self._new_scheduler
        else:
            self._controller_factories = dict(controller_factories)
        try:
            self.controllers, self.runner = self._prepare()
        except BaseException:
            if self._source60 and self.random_session is not None:
                self.random_session.close()
            raise
        self.scheduler = self.controllers.get('tank-2')

    def _new_scheduler(self):
        if self._factory is not None:
            return self._factory()
        return create_desktop_scheduler(self.strategy)

    def _prepare(self):
        candidate = {}
        owned = {id(c) for c in self.controllers.values()}
        try:
            for tid, factory in self._controller_factories.items():
                controller = factory()
                if id(controller) in owned or any(controller is c for c in candidate.values()):
                    raise ValueError('controller factories must create distinct fresh instances')
                candidate[tid] = controller
            runner = MatchRunner(self.world, candidate)
        except Exception:
            _close_all(candidate, excluding=owned)
            raise
        return candidate, runner

    def transition(self, operation, *, allow_active=False):
        if self._closed:
            return False
        if operation not in ('retry', 'next_map'):
            raise ValueError('choose retry or next_map')
        if self.world.observe('tank-1')['round_status'] != 'GAME_OVER' and not allow_active:
            return False
        if not self._random_requested and operation == 'next_map':
            return False
        candidate, runner = self._prepare()
        try:
            changed = (self.random_session.transition(operation, allow_active=allow_active)
                       if self.random_session is not None
                       else self.world.restart(allow_active=allow_active))
        except Exception:
            _close_all(candidate)
            raise
        if not changed:
            _close_all(candidate)
            return False
        old = self.controllers
        self.controllers, self.runner = candidate, runner
        self.scheduler = candidate.get('tank-2')
        _close_all(old)
        return True

    def close(self):
        if not self._closed:
            self._closed = True
            _close_all(self.controllers)
            if self._source60 and self.random_session is not None:
                self.random_session.close()
