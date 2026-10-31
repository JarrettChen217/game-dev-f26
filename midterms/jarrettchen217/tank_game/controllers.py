"""Translate sampled human input into the same public requests used by bots."""

from typing import Protocol

from tank_game.actions import Action


def keyboard_request(scene: dict, held: set[str], *, fire_pressed: bool = False) -> dict:
    """Aliases count once; shooting is a press event, never a held-key repeat.

    This adapter receives only detached public data and logical held-key names.
    It has no reference to the simulation or to the window/input library.
    """
    throttle = int(bool(held & {'forward', 'w', 'up'})) - int(bool(held & {'backward', 's', 'down'}))
    turn = int(bool(held & {'turn_right', 'd', 'right'})) - int(bool(held & {'turn_left', 'a', 'left'}))
    return {'round_id': scene['round_id'], 'observation_tick': scene['observation_tick'],
            'tank_id': scene['self_id'], 'throttle': throttle, 'turn': turn, 'fire': fire_pressed}


class Controller(Protocol):
    def request(self, scene: dict) -> dict: ...
    def pause(self, scene: dict) -> None: ...
    def close(self) -> None: ...


class BufferedController:
    """Latest axes and one pending fire edge; independent of devices and World."""

    def __init__(self, *, hold_fire=False):
        self._hold_fire = hold_fire
        self._action = Action()
        self._fire_edge = False
        self._closed = False

    def set_input(self, action: Action) -> None:
        if self._closed:
            raise RuntimeError('controller is closed')
        if not isinstance(action, Action):
            raise TypeError('expected Action')
        if self._hold_fire and action.fire and not self._action.fire:
            self._fire_edge = True
        self._action = (action if self._hold_fire else
                        Action(action.throttle, action.turn, action.fire or self._action.fire))

    def request(self, scene: dict) -> dict:
        if self._closed or scene['round_status'] != 'PLAYING' or not scene['self_status']['alive']:
            self._action = Action()
            self._fire_edge = False
        held = self._action
        action = Action(held.throttle, held.turn, held.fire or self._fire_edge)
        self._fire_edge = False
        self._action = held if self._hold_fire else Action(action.throttle, action.turn)
        request = keyboard_request(scene, set())
        request.update(throttle=action.throttle, turn=action.turn, fire=action.fire)
        return request

    def pause(self, scene: dict) -> None:
        self._action = Action()
        self._fire_edge = False

    def close(self) -> None:
        self._action = Action()
        self._fire_edge = False
        self._closed = True
