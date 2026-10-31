"""State-scoped keyboard routing; no world mutation or competitive restart action."""

from tank_game.controllers import keyboard_request
from tank_game.keymap import GAMEPLAY_ACTIONS


class StateKeyboard:
    def __init__(self, pyxel, keys, *, release_keys=()):
        self.pyxel = pyxel
        self.keys = keys
        self.release_keys = release_keys
        self.wait_for_release = False
        self.next_map_enabled = False

    def _pressed(self, action):
        return any(self.pyxel.btnp(key) for key in self.keys[action])

    def read(self, scene: dict) -> tuple[dict | None, bool]:
        phase = scene['round_status']
        if phase == 'GAME_OVER':
            return None, self.read_postgame(scene) == 'retry'
        if phase != 'PLAYING':
            return None, False
        if self.wait_for_release:
            actions = GAMEPLAY_ACTIONS + ('restart',)
            if self.next_map_enabled:
                actions += ('next_map',)
            down = any(self.pyxel.btn(key) or self.pyxel.btnp(key)
                       for action in actions for key in self.keys[action])
            down |= any(self.pyxel.btn(key) or self.pyxel.btnp(key) for key in self.release_keys)
            if not down:
                self.wait_for_release = False
            return None, False
        held = {action for action in GAMEPLAY_ACTIONS if action != 'fire'
                and any(self.pyxel.btn(key) for key in self.keys[action])}
        fire = self._pressed('fire')
        if scene.get('research', {}).get('profile') == 'killfield-rules-v2':
            fire = fire or any(self.pyxel.btn(key) for key in self.keys['fire'])
        return keyboard_request(scene, held, fire_pressed=fire), False

    def read_postgame(self, scene: dict, *, allow_next_map=False) -> str | None:
        if scene['round_status'] != 'GAME_OVER':
            return None
        self.next_map_enabled = allow_next_map
        operation = ('retry' if self._pressed('restart') else
                     'next_map' if allow_next_map and self._pressed('next_map') else None)
        if operation:
            self.wait_for_release = True
        return operation
