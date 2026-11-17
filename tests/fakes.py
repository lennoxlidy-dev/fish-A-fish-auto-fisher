"""Fake clock / input / screen plus a tiny simulated fishing game for the tests."""
from __future__ import annotations

import copy
import math
from typing import Callable, List, Optional, Tuple

import numpy as np

from autofisher.config import DEFAULTS, MOUSE
from autofisher.inputs import InputBackend

WATER = (30, 60, 120)
RED = (255, 0, 0)
TRACK = (40, 40, 40)
GREEN = (100, 220, 100)
YELLOW = (240, 200, 40)
WHITE = (250, 250, 250)


def make_cfg(**overrides) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    cfg["humanize"]["timing_jitter"] = 0.0
    cfg["humanize"]["click_jitter_px"] = 0
    for path, value in overrides.items():
        node = cfg
        keys = path.split("__")
        for k in keys[:-1]:
            node = node[k]
        node[keys[-1]] = value
    return cfg


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.on_advance: List[Callable[[float], None]] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, dt: float) -> None:
        # advance in small steps so the simulated game stays smooth
        while dt > 0:
            step = min(dt, 0.005)
            self.now += step
            dt = dt - step if dt - step > 1e-9 else 0.0
            for cb in self.on_advance:
                cb(step)


class FakeInput(InputBackend):
    def __init__(self, clock: FakeClock) -> None:
        super().__init__()
        self.clock = clock
        self.events: List[Tuple[float, str, str]] = []
        self.pos = (500, 500)
        self.on_event: List[Callable[[str, str], None]] = []

    def _record(self, kind: str, name: str) -> None:
        self.events.append((self.clock.now, kind, name))
        for cb in self.on_event:
            cb(kind, name)

    def _mouse_down(self) -> None:
        self._record("down", MOUSE)

    def _mouse_up(self) -> None:
        self._record("up", MOUSE)

    def _key_down(self, name: str) -> None:
        self._record("down", name)

    def _key_up(self, name: str) -> None:
        self._record("up", name)

    def move(self, x: int, y: int) -> None:
        self.pos = (x, y)

    def position(self):
        return self.pos

    def downs(self, name: str = MOUSE, since: float = float("-inf"), until: float = float("inf")) -> int:
        return sum(1 for t, k, n in self.events if k == "down" and n == name and since <= t < until)


class Canvas:
    """A fake screen: grab() crops from an image produced by render()."""

    def __init__(self, render: Callable[[], np.ndarray]) -> None:
        self.render = render

    def grab(self, region):
        x, y, w, h = region
        return self.render()[y:y + h, x:x + w].copy()

    def pixel(self, x, y):
        return tuple(int(v) for v in self.render()[y, x])


class FishingGame:
    """Cast -> '!' appears -> click to hook -> keep the yellow fish inside your green bar.

    Holding the mouse pushes the bar right, letting go lets it fall back left,
    like most Roblox fishing games. Progress fills while the fish is in the bar.
    """

    W, H = 400, 200
    BITE_REGION = [180, 20, 20, 20]
    BAR_REGION = [50, 100, 300, 20]
    BAR_HALF = 30

    def __init__(self, clock: FakeClock, inputs: FakeInput, bite_delay: float = 2.0) -> None:
        self.clock = clock
        self.inputs = inputs
        self.bite_delay = bite_delay
        self.phase = "idle"
        self.bite_at = 0.0
        self.caught = 0
        self.lost = 0
        self.frames_in_bar = 0
        self.frames_reeling = 0
        self._reset_minigame()
        clock.on_advance.append(self.step)
        inputs.on_event.append(self.on_input)

    def _reset_minigame(self) -> None:
        self.bar = 40.0
        self.bar_vel = 0.0
        self.progress = 0.3
        self.t0 = self.clock.now

    def fish(self) -> float:
        t = self.clock.now - self.t0
        return 150 + 100 * math.sin(0.8 * t) + 25 * math.sin(2.1 * t + 1)

    def on_input(self, kind: str, name: str) -> None:
        if kind != "down" or name != MOUSE:
            return
        if self.phase == "idle":
            self.phase = "waiting"
            self.bite_at = self.clock.now + self.bite_delay
        elif self.phase == "bite":
            self.phase = "reeling"
            self._reset_minigame()

    def step(self, dt: float) -> None:
        if self.phase == "waiting" and self.clock.now >= self.bite_at:
            self.phase = "bite"
        if self.phase != "reeling":
            return
        accel = 900.0 if self.inputs.is_held(MOUSE) else -900.0
        self.bar_vel = max(-400.0, min(400.0, self.bar_vel + accel * dt))
        self.bar += self.bar_vel * dt
        lo, hi = self.BAR_HALF, self.BAR_REGION[2] - 1 - self.BAR_HALF
        if self.bar < lo or self.bar > hi:
            self.bar = max(lo, min(hi, self.bar))
            self.bar_vel = 0.0
        inside = abs(self.fish() - self.bar) <= self.BAR_HALF
        self.frames_reeling += 1
        self.frames_in_bar += inside
        self.progress += (0.35 if inside else -0.25) * dt
        if self.progress >= 1.0:
            self.caught += 1
            self.phase = "idle"
        elif self.progress <= 0.0:
            self.lost += 1
            self.phase = "idle"

    def render(self) -> np.ndarray:
        img = np.empty((self.H, self.W, 3), dtype=np.uint8)
        img[:] = WATER
        if self.phase == "bite":
            x, y, w, h = self.BITE_REGION
            img[y + 4:y + h - 4, x + 7:x + 13] = RED  # the "!"
        if self.phase == "reeling":
            x, y, w, h = self.BAR_REGION
            img[y:y + h, x:x + w] = TRACK
            b0 = int(round(self.bar)) - self.BAR_HALF
            img[y:y + h, x + max(0, b0):x + min(w, b0 + 2 * self.BAR_HALF + 1)] = GREEN
            f = int(round(self.fish()))
            img[y + 3:y + h - 3, x + max(0, f - 4):x + min(w, f + 5)] = YELLOW
        return img
