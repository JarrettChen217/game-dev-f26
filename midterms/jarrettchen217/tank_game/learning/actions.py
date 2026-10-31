"""Versioned joint action mapping, independent of numerical/model libraries."""
from tank_game.actions import Action


def encode_action(action: Action) -> int:
    if not isinstance(action,Action):
        raise TypeError('expected Action')
    return 2*(3*(action.throttle+1)+action.turn+1)+int(action.fire)


def decode_action(index: int) -> Action:
    if type(index) is not int or not 0<=index<18:
        raise ValueError('action index must be an integer in0..17')
    movement,fire=divmod(index,2)
    throttle,turn=divmod(movement,3)
    return Action(throttle-1,turn-1,bool(fire))
