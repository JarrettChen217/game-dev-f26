"""Lightweight window metadata without OS/library access."""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class WindowSnapshot:
    focused: bool
    viewport_token: tuple
    inside_canvas: bool


class WindowObserver(Protocol):
    def sample(self, pyxel) -> WindowSnapshot: ...
    def close(self) -> None: ...
