"""A captured gesture cannot change owner, target, page or layout."""
from dataclasses import dataclass

from tank_game.window_contract import WindowSnapshot


@dataclass(frozen=True)
class InteractionFrame:
    position: tuple[int, int]
    window: WindowSnapshot
    pressed: bool = False
    held: bool = False
    released: bool = False
    confirm_pressed: bool = False
    confirm_held: bool = False
    confirm_released: bool = False
    keyboard_control: str | None = None
    navigation: str | None = None
    escape_pressed: bool = False
    all_released: bool = True


@dataclass(frozen=True)
class InteractionResult:
    focus_control: str | None = None
    activate_control: str | None = None
    pressed_control: str | None = None
    cancelled: bool = False


class MenuInteraction:
    def __init__(self):
        self.target = None
        self.source = None
        self._token = None
        self._position = None
        self._blocked = False

    def invalidate(self):
        self.target = self.source = None
        self._blocked = True

    def update(self, frame, controls, *, context_token):
        token = (context_token, frame.window.viewport_token,
                 tuple((c.id, c.rect, c.operation, c.value) for c in controls))
        changed = self._token is not None and token != self._token
        moved = self._position is not None and frame.position != self._position
        self._token, self._position = token, frame.position
        idle = frame.all_released and not any((frame.pressed, frame.held, frame.released,
                frame.confirm_pressed, frame.confirm_held, frame.confirm_released))
        if changed or not frame.window.focused or frame.escape_pressed:
            self.invalidate()
            if changed and frame.window.focused and not frame.escape_pressed and idle:
                self._blocked = False
            return InteractionResult(cancelled=True)
        if self._blocked:
            if idle:
                self._blocked = False
            return InteractionResult()
        hit = next((c for c in controls if frame.window.inside_canvas
                    and c.contains(frame.position)), None)
        if self.target is None:
            if frame.confirm_pressed and frame.keyboard_control:
                self.target, self.source = frame.keyboard_control, 'keyboard'
            elif frame.pressed and hit and hit.operation is not None:
                self.target, self.source = hit.id, 'mouse'
            elif (moved or frame.pressed) and not frame.navigation and hit:
                return InteractionResult(focus_control=hit.id)
        if self.target is None:
            return InteractionResult()
        target, source = self.target, self.source
        inside = source == 'keyboard' or (hit is not None and hit.id == target)
        released = frame.confirm_released if source == 'keyboard' else frame.released
        if released:
            self.target = self.source = None
            return InteractionResult(focus_control=target, activate_control=target if inside else None)
        return InteractionResult(focus_control=target, pressed_control=target if inside else None)
