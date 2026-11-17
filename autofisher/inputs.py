"""Sending mouse clicks and key presses.

Roblox ignores some kinds of fake input, so on Windows we use pydirectinput,
which sends hardware scan codes through SendInput (what DirectX games listen
to). On macOS / Linux we fall back to pynput.
"""
from __future__ import annotations

import sys
from typing import Optional, Set, Tuple

from .config import MOUSE


class InputBackend:
    """Tracks what is held down so everything can be released on pause/quit."""

    def __init__(self) -> None:
        self._held: Set[str] = set()

    # -- public API used by the bot
    def down(self, name: str) -> None:
        if name == MOUSE:
            self._mouse_down()
        else:
            self._key_down(name)
        self._held.add(name)

    def up(self, name: str) -> None:
        try:
            if name == MOUSE:
                self._mouse_up()
            else:
                self._key_up(name)
        finally:
            self._held.discard(name)

    def is_held(self, name: str) -> bool:
        return name in self._held

    def release_all(self) -> None:
        for name in list(self._held):
            try:
                self.up(name)
            except Exception:
                pass
        self._held.clear()

    def move(self, x: int, y: int) -> None:
        raise NotImplementedError

    def position(self) -> Optional[Tuple[int, int]]:
        return None

    def validate_key(self, name: str) -> bool:
        return True

    # -- implemented by subclasses
    def _mouse_down(self) -> None:
        raise NotImplementedError

    def _mouse_up(self) -> None:
        raise NotImplementedError

    def _key_down(self, name: str) -> None:
        raise NotImplementedError

    def _key_up(self, name: str) -> None:
        raise NotImplementedError


class DirectInputBackend(InputBackend):
    """Windows: pydirectinput (scan-code SendInput, works with Roblox)."""

    def __init__(self) -> None:
        super().__init__()
        import pydirectinput  # type: ignore

        pydirectinput.PAUSE = 0          # default is a 0.1 s sleep after *every* call
        pydirectinput.FAILSAFE = False   # we run our own corner fail-safe check
        self._pdi = pydirectinput

    def validate_key(self, name: str) -> bool:
        return name in self._pdi.KEYBOARD_MAPPING

    def _mouse_down(self) -> None:
        self._pdi.mouseDown(button="left")

    def _mouse_up(self) -> None:
        self._pdi.mouseUp(button="left")

    def _key_down(self, name: str) -> None:
        self._pdi.keyDown(name)

    def _key_up(self, name: str) -> None:
        self._pdi.keyUp(name)

    def move(self, x: int, y: int) -> None:
        self._pdi.moveTo(int(x), int(y))

    def position(self) -> Optional[Tuple[int, int]]:
        x, y = self._pdi.position()
        return int(x), int(y)


class PynputBackend(InputBackend):
    """macOS / Linux fallback."""

    def __init__(self) -> None:
        super().__init__()
        from pynput import keyboard, mouse  # type: ignore

        self._mouse = mouse.Controller()
        self._kb = keyboard.Controller()
        self._button = mouse.Button.left
        self._Key = keyboard.Key

    def _resolve(self, name: str):
        if len(name) == 1:
            return name
        key = getattr(self._Key, name, None)
        if key is None:
            raise ValueError(f"unknown key name {name!r}")
        return key

    def validate_key(self, name: str) -> bool:
        try:
            self._resolve(name)
            return True
        except ValueError:
            return False

    def _mouse_down(self) -> None:
        self._mouse.press(self._button)

    def _mouse_up(self) -> None:
        self._mouse.release(self._button)

    def _key_down(self, name: str) -> None:
        self._kb.press(self._resolve(name))

    def _key_up(self, name: str) -> None:
        self._kb.release(self._resolve(name))

    def move(self, x: int, y: int) -> None:
        self._mouse.position = (int(x), int(y))

    def position(self) -> Optional[Tuple[int, int]]:
        x, y = self._mouse.position
        return int(x), int(y)


def create_input_backend() -> InputBackend:
    if sys.platform == "win32":
        try:
            return DirectInputBackend()
        except ImportError:
            raise SystemExit("pydirectinput is not installed. Run:  python -m pip install -r requirements.txt")
    try:
        return PynputBackend()
    except ImportError:
        raise SystemExit("pynput is not installed. Run:  python -m pip install -r requirements.txt")
