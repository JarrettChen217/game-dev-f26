"""Normal policy interface with shared preprocessing; no model/checkpoint loader."""
from collections.abc import Callable

import numpy as np

from tank_game.controllers import keyboard_request
from tank_game.learning.actions import decode_action
from tank_game.learning.encoding import ObservationEncoder


class EncodedPolicy:
    version='encoded-test-policy-v1'

    def __init__(self,predict: Callable[[np.ndarray],int]):
        self.predict=predict
        self.encoder=ObservationEncoder()
        self._round=None
        self._tick=None
        self._previous=None
        self._input_previous=None
        self._response=None

    def decide(self,scene: dict) -> dict:
        if self._round!=scene['round_id']:
            self.encoder.reset();self._previous=None;self._tick=None
            self._round=scene['round_id']
        duplicate=self._tick==scene['observation_tick']
        prior=self._input_previous if duplicate else self._previous
        tensor=self.encoder.encode(scene,prior)
        if duplicate:return dict(self._response)
        action=decode_action(self.predict(tensor))
        request=keyboard_request(scene,set())
        request.update(throttle=action.throttle,turn=action.turn,fire=action.fire)
        self._input_previous=prior;self._previous=action
        self._tick=scene['observation_tick'];self._response=request
        return dict(request)
