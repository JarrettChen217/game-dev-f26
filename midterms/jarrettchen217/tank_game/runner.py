"""One deterministic match tick; resources and wall time belong to the host."""
from collections.abc import Mapping
from typing import Protocol

from tank_game.controllers import Controller
from tank_game.world import World


class TickRecorder(Protocol):
    """Trusted read-only observer; retained data must be copied by the recorder."""
    def begin_tick(self, tick: int, phase: str) -> None: ...
    def before_request(self, tank_id: str, scene: dict) -> None: ...
    def after_request(self, tank_id: str, scene: dict, request: dict, *, submitted: bool) -> None: ...
    def end_tick(self) -> None: ...


class MatchRunner:
    def __init__(self, world: World, controllers: Mapping[str, Controller], *,
                 recorder: TickRecorder | None = None):
        for tank_id in controllers:
            world.observe(tank_id)  # Validate bindings through the authoritative interface.
        self.world = world
        self.controllers = dict(controllers)
        self.recorder = recorder

    def tick(self) -> None:
        views = [(tid, controller, self.world.observe(tid))
                 for tid, controller in self.controllers.items()]
        recorder = self.recorder
        if recorder is not None:
            public = views[0][2] if views else self.world.observe('tank-1')
            recorder.begin_tick(public['observation_tick'], public['round_status'])
        for tid, controller, scene in views:
            if recorder is not None:
                recorder.before_request(tid, scene)
            submitted = scene['round_status'] == 'PLAYING' and scene['self_status']['alive']
            request = controller.request(scene)
            if submitted:
                self.world.submit_action(tid, request)
            if recorder is not None:
                recorder.after_request(tid, scene, request, submitted=submitted)
        self.world.step()
        if recorder is not None:
            recorder.end_tick()

    def pause(self) -> None:
        for tid, controller in self.controllers.items():
            controller.pause(self.world.observe(tid))
