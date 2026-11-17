"""Start / pause / quit state and the global hotkeys (F6 / F7 / F8 by default)."""
from __future__ import annotations

import threading
from typing import Callable, Dict, Optional, Set


class Controls:
    def __init__(self, start_paused: bool = True, log: Callable[[str], None] = print) -> None:
        self._running = threading.Event()
        self._quit = threading.Event()
        self._log = log
        if not start_paused:
            self._running.set()

    @property
    def running(self) -> bool:
        return self._running.is_set()

    @property
    def quit(self) -> bool:
        return self._quit.is_set()

    def start(self) -> None:
        self._running.set()
        self._log(">> RUNNING (press the toggle key again to pause)")

    def pause(self) -> None:
        if self._running.is_set():
            self._running.clear()
            self._log("|| PAUSED")

    def toggle(self) -> None:
        if self.running:
            self.pause()
        else:
            self.start()

    def request_quit(self) -> None:
        self._log("Quitting...")
        self._quit.set()
        self._running.set()  # wake anything waiting to run so it can see quit

    def wait_until_running(self, timeout: Optional[float] = None) -> bool:
        return self._running.wait(timeout)


def key_name(key) -> Optional[str]:
    """Turn a pynput key object into a lowercase name like "f6", "e" or "space"."""
    char = getattr(key, "char", None)
    if char:
        return char.lower()
    name = getattr(key, "name", None)
    if name:
        return name.lower()
    return None


class HotkeyListener:
    """Global hotkeys that work while Roblox is the active window."""

    def __init__(self, bindings: Dict[str, Callable[[], None]]) -> None:
        self.bindings = {k.lower(): v for k, v in bindings.items()}
        self._down: Set[str] = set()
        self._listener = None

    def start(self) -> "HotkeyListener":
        try:
            from pynput import keyboard  # type: ignore
        except ImportError:
            raise SystemExit("pynput is not installed. Run:  python -m pip install -r requirements.txt")
        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.daemon = True
        self._listener.start()
        return self

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()

    def _on_press(self, key) -> None:
        name = key_name(key)
        if name is None or name in self._down:  # ignore auto-repeat while held
            return
        self._down.add(name)
        callback = self.bindings.get(name)
        if callback is not None:
            try:
                callback()
            except Exception as e:  # never let a hotkey crash the listener thread
                print(f"[hotkey {name}] error: {e}")

    def _on_release(self, key) -> None:
        name = key_name(key)
        if name is not None:
            self._down.discard(name)
