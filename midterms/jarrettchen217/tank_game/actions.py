"""Strict, identity-bound action ingress shared by every controller."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Action:
    throttle: int = 0
    turn: int = 0
    fire: bool = False

    def __post_init__(self):
        if any(type(axis) is not int or axis not in (-1, 0, 1)
               for axis in (self.throttle, self.turn)) or type(self.fire) is not bool:
            raise ValueError('Action requires integer axes and a boolean fire request')


def validate_request(data: object, *, source_id: str, round_id: int, tick: int) -> Action | None:
    """None means rejection, distinct from a successfully submitted idle action."""
    keys = {'round_id', 'observation_tick', 'tank_id', 'throttle', 'turn', 'fire'}
    if type(data) is not dict or set(data) != keys:
        return None
    if (type(data['round_id']) is not int or data['round_id'] != round_id
            or type(data['observation_tick']) is not int or data['observation_tick'] != tick
            or type(data['tank_id']) is not str or data['tank_id'] != source_id):
        return None
    try:
        return Action(data['throttle'], data['turn'], data['fire'])
    except ValueError:
        return None
