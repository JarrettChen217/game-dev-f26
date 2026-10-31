"""Validated, immutable startup keyboard configuration; no window dependency."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from string import ascii_uppercase, digits
from types import MappingProxyType

DEFAULT_KEYMAP_PATH = Path(__file__).resolve().parents[1] / 'keymap.json'
GAMEPLAY_ACTIONS = ('forward', 'backward', 'turn_left', 'turn_right', 'fire')
GLOBAL_ACTIONS = ('quit', 'inspection_previous', 'inspection_next')
UI_ACTIONS = ('inspection_toggle',)
POSTGAME_ACTIONS = ('restart', 'next_map')
ACTIONS = GAMEPLAY_ACTIONS + GLOBAL_ACTIONS + POSTGAME_ACTIONS + UI_ACTIONS
SUPPORTED_KEYS = frozenset(ascii_uppercase + digits) | frozenset(
    ('UP', 'DOWN', 'LEFT', 'RIGHT', 'SPACE', 'RETURN', 'ESCAPE', 'TAB', 'BACKSPACE',
     'DELETE', 'INSERT', 'HOME', 'END', 'PAGEUP', 'PAGEDOWN', 'SHIFT', 'CTRL', 'ALT',
     'LSHIFT', 'RSHIFT', 'LCTRL', 'RCTRL', 'LALT', 'RALT', 'MINUS', 'EQUALS', 'COMMA',
     'PERIOD', 'SLASH', 'SEMICOLON', 'QUOTE', 'LEFTBRACKET', 'RIGHTBRACKET', 'BACKSLASH',
     'BACKQUOTE') + tuple(f'F{i}' for i in range(1, 13)))


class KeymapError(ValueError):
    """A user-editable file failed loading or binding validation."""


def _physical_keys(name):
    return (f'L{name}', f'R{name}') if name in {'SHIFT', 'CTRL', 'ALT'} else (name,)


@dataclass(frozen=True)
class Keymap:
    bindings: Mapping[str, tuple[str, ...]]
    source: Path

    def names(self, action: str) -> tuple[str, ...]:
        return self.bindings[action]

    def validate_mode(self, *, random_map=False):
        """Validate mode-specific activation against the startup snapshot."""
        if random_map:
            active = GAMEPLAY_ACTIONS + GLOBAL_ACTIONS + UI_ACTIONS + ('restart',)
            for name in self.names('next_map'):
                if name in {'UP', 'DOWN', 'RETURN', 'ESCAPE'}:
                    raise KeymapError(f'next_map: {name} conflicts with results navigation')
                for action in active:
                    if any(set(_physical_keys(name)) & set(_physical_keys(other))
                           for other in self.names(action)):
                        raise KeymapError(f'next_map: {name} overlaps {action}')

    def resolve(self, pyxel) -> Mapping[str, tuple]:
        resolved = {}
        for action, names in self.bindings.items():
            try:
                resolved[action] = tuple(getattr(pyxel, f'KEY_{name}') for name in names)
            except AttributeError as error:
                raise KeymapError(f'{self.source}: {action}: key unavailable in this engine: '
                                  f'{error}') from error
        return MappingProxyType(resolved)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise KeymapError(f'duplicate JSON field: {key}')
        result[key] = value
    return result


def load_keymap(path: Path | str | None = None, *, enable_next_map=False, enable_ui=False) -> Keymap:
    """Read once per app launch. Invalid/missing files fail visibly, never reset."""
    source = Path(path).resolve() if path is not None else DEFAULT_KEYMAP_PATH
    try:
        data = json.loads(source.read_text(encoding='utf-8'), object_pairs_hook=_unique_object)
        if type(data) is not dict or set(data) != {'version', 'bindings'}:
            raise KeymapError('expected version and bindings fields only')
        if type(data['version']) is not int or data['version'] != 1:
            raise KeymapError('version must be 1')
        bindings = data['bindings']
        if type(bindings) is not dict:
            raise KeymapError('bindings must be an object')
        # Older v1 files gain the new postgame default without being rewritten.
        bindings = {**bindings}
        bindings.setdefault('restart', ['SPACE'])
        bindings.setdefault('next_map', ['N'])
        bindings.setdefault('inspection_toggle', ['TAB'])
        if set(bindings) != set(ACTIONS):
            raise KeymapError(f'bindings: missing {sorted(set(ACTIONS) - set(bindings))}; '
                              f'unknown {sorted(set(bindings) - set(ACTIONS))}')
        normalized, used = {}, {}
        contexts = {action: frozenset(('PLAYING',)) for action in GAMEPLAY_ACTIONS}
        contexts.update({action: frozenset(('GAME_OVER',)) for action in POSTGAME_ACTIONS})
        contexts.update({action: frozenset(('PLAYING', 'DYING', 'GAME_OVER'))
                         for action in GLOBAL_ACTIONS})
        contexts['inspection_toggle'] = (frozenset(('PLAYING', 'DYING', 'GAME_OVER'))
                                         if enable_ui else frozenset())
        contexts['next_map'] = (frozenset(('PLAYING', 'DYING', 'GAME_OVER'))
                                if enable_next_map else frozenset())
        for action in ACTIONS:
            names = bindings[action]
            if type(names) is not list or not names:
                raise KeymapError(f'{action}: expected a nonempty list of key names')
            result = []
            for name in names:
                if type(name) is not str or name.strip().upper() not in SUPPORTED_KEYS:
                    raise KeymapError(f'{action}: unsupported key {name!r}')
                name = name.strip().upper()
                # Aggregate modifier buttons include their left/right physical keys.
                physical = _physical_keys(name)
                for key in physical:
                    for previous in used.get(key, []):
                        if contexts[action] & contexts[previous]:
                            raise KeymapError(
                                f'{action}: {name} overlaps {key} bound to {previous}')
                    used.setdefault(key, []).append(action)
                result.append(name)
            normalized[action] = tuple(result)
        if enable_ui:
            reserved = {'UP', 'DOWN', 'RETURN', 'ESCAPE'}
            for action in ('restart', 'next_map', 'quit', 'inspection_previous',
                           'inspection_next', 'inspection_toggle'):
                if action == 'next_map' and not enable_next_map:
                    continue
                for name in normalized[action]:
                    if name in reserved and not (action == 'quit' and name == 'ESCAPE'):
                        raise KeymapError(f'{action}: {name} conflicts with menu/results navigation')
            for name in normalized['quit']:
                if name in {'LEFT', 'RIGHT'}:
                    raise KeymapError(f'quit: {name} conflicts with menu navigation')
        return Keymap(MappingProxyType(normalized), source)
    except (OSError, UnicodeError, json.JSONDecodeError, KeymapError) as error:
        raise KeymapError(f'{source}: {error}') from error
