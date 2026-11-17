"""The fishing loop: cast -> wait for a bite -> reel -> clean up -> repeat.

Screen, input, clock and sleep are passed in, so the whole loop can be tested
against a simulated game (see tests/test_bot.py).
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Callable, Optional, Sequence, Tuple

from .config import MOUSE
from .vision import Detector, blob_center, color_mask, find_span, span_center


class Interrupted(Exception):
    """Stop the current cycle right now (paused, quitting, or Roblox lost focus)."""


@dataclass
class Stats:
    started: float
    reels: int = 0
    missed: int = 0
    no_bites: int = 0

    def per_hour(self, now: float) -> float:
        return self.reels * 3600.0 / max(now - self.started, 1e-6)


class Presser:
    """Non-blocking tap: press now, release on a later update() once `hold` seconds have passed."""

    def __init__(self, inputs, name: str, hold: float = 0.03) -> None:
        self.inputs = inputs
        self.name = name
        self.hold = hold
        self.held_since: Optional[float] = None

    @property
    def held(self) -> bool:
        return self.held_since is not None

    def press(self, now: float) -> None:
        if self.held_since is None:
            self.inputs.down(self.name)
            self.held_since = now

    def update(self, now: float) -> None:
        if self.held_since is not None and now - self.held_since >= self.hold:
            self.inputs.up(self.name)
            self.held_since = None


class BarController:
    """Decides hold/release to keep your bar on top of the fish.

    Positions are pixels along the bar. The bar's speed is estimated from frame
    to frame and used to predict where it will be `lookahead` seconds from now,
    which stops it from overshooting.
    """

    def __init__(self, positive: bool = True, deadzone: float = 4.0, lookahead: float = 0.15,
                 smoothing: float = 0.5) -> None:
        self.positive = positive
        self.deadzone = deadzone
        self.lookahead = lookahead
        self.smoothing = smoothing
        self.velocity = 0.0
        self.holding = False
        self._prev: Optional[Tuple[float, float]] = None

    def update(self, fish: Optional[float], bar: Optional[float], now: float) -> bool:
        if bar is not None:
            if self._prev is not None:
                dt = now - self._prev[1]
                if dt > 1e-4:
                    inst = (bar - self._prev[0]) / dt
                    self.velocity = self.smoothing * self.velocity + (1 - self.smoothing) * inst
            self._prev = (bar, now)
        if fish is None or bar is None:
            return self.holding
        error = fish - (bar + self.velocity * self.lookahead)
        if not self.positive:
            error = -error
        if error > self.deadzone:
            self.holding = True
        elif error < -self.deadzone:
            self.holding = False
        return self.holding


class ZoneTrigger:
    """Fires once when a moving marker is (about to be) inside the target zone."""

    def __init__(self, margin: float = 2.0, lookahead: float = 0.03, cooldown: float = 0.3,
                 smoothing: float = 0.5) -> None:
        self.margin = margin
        self.lookahead = lookahead
        self.cooldown = cooldown
        self.smoothing = smoothing
        self.velocity = 0.0
        self._prev: Optional[Tuple[float, float]] = None
        self._last_fire = float("-inf")

    def update(self, marker: Optional[float], zone: Optional[Tuple[float, float]], now: float) -> bool:
        if marker is None:
            self._prev = None
            return False
        if self._prev is not None:
            dt = now - self._prev[1]
            if dt > 1e-4:
                inst = (marker - self._prev[0]) / dt
                self.velocity = self.smoothing * self.velocity + (1 - self.smoothing) * inst
        self._prev = (marker, now)
        if zone is None or now - self._last_fire < self.cooldown:
            return False
        lo, hi = zone[0] + self.margin, zone[1] - self.margin
        if lo > hi:
            lo = hi = (zone[0] + zone[1]) / 2.0
        # Must be inside now AND still inside by the time the press lands.
        predicted = marker + self.velocity * self.lookahead
        if lo <= marker <= hi and lo <= predicted <= hi:
            self._last_fire = now
            return True
        return False


StepFn = Callable[[float], Optional[bool]]


class FishingBot:
    def __init__(self, cfg: dict, screen, inputs, controls, *,
                 clock: Callable[[], float] = time.monotonic,
                 sleeper: Callable[[float], None] = time.sleep,
                 focus_check: Optional[Callable[[], Optional[bool]]] = None,
                 log: Callable[[str], None] = print,
                 rng: Optional[random.Random] = None) -> None:
        self.cfg = cfg
        self.screen = screen
        self.inputs = inputs
        self.controls = controls
        self.clock = clock
        self.sleeper = sleeper
        self.focus_check = focus_check
        self.log = log
        self.rng = rng or random.Random()
        self.tick = 1.0 / cfg["loop_hz"]
        self.stats = Stats(started=clock())
        self._since_sell = 0
        self._last_focus_check = float("-inf")

    # ------------------------------------------------------------ main loop

    def run(self, max_cycles: Optional[int] = None) -> None:
        cycles = 0
        while not self.controls.quit:
            if max_cycles is not None and cycles >= max_cycles:
                break
            if not self.controls.running:
                self.inputs.release_all()
                self.controls.wait_until_running(timeout=0.2)
                continue
            try:
                self.cycle()
            except Interrupted:
                pass
            finally:
                self.inputs.release_all()
            cycles += 1

    def cycle(self) -> None:
        self.cast()
        if not self.wait_for_bite():
            self.stats.no_bites += 1
            self.log(f"No bite within {self.cfg['bite']['timeout']:.0f}s - recasting.")
            self.run_actions(self.cfg["bite"]["on_timeout"])
            return
        if self.reel():
            self.stats.reels += 1
            self._since_sell += 1
        else:
            self.stats.missed += 1
        self.log(self.status_line())
        self.run_actions(self.cfg["after_catch"]["actions"])
        self.sleep(self.jitter(self.cfg["after_catch"]["wait"]))
        sell = self.cfg["auto_sell"]
        if sell["enabled"] and self._since_sell >= sell["every"]:
            self.log("Auto-selling...")
            self.run_actions(sell["actions"])
            self._since_sell = 0

    def status_line(self) -> str:
        s = self.stats
        return (f"[{time.strftime('%H:%M:%S')}] reels: {s.reels} | missed: {s.missed} | "
                f"no bite: {s.no_bites} | {s.per_hour(self.clock()):.0f}/hour")

    # ------------------------------------------------------------ helpers

    def check(self) -> None:
        """Called constantly; raises Interrupted when the bot has to stop what it's doing."""
        if self.controls.quit or not self.controls.running:
            raise Interrupted()
        pos = self.inputs.position()
        if pos is not None and pos[0] <= 2 and pos[1] <= 2:
            self.log("Mouse is in the top-left corner - fail-safe, pausing.")
            self.controls.pause()
            raise Interrupted()
        if self.focus_check is not None:
            now = self.clock()
            if now - self._last_focus_check >= 0.25:
                self._last_focus_check = now
                if self.focus_check() is False:
                    self._wait_for_focus()

    def _wait_for_focus(self) -> None:
        self.inputs.release_all()
        self.log("Roblox is not the active window - waiting. Click on Roblox to continue.")
        while self.focus_check() is False:
            if self.controls.quit or not self.controls.running:
                raise Interrupted()
            self.sleeper(0.25)
        self.log("Roblox is active again - starting over from the cast.")
        self.sleeper(0.5)
        raise Interrupted()

    def sleep(self, seconds: float) -> None:
        end = self.clock() + max(0.0, seconds)
        while True:
            self.check()
            remaining = end - self.clock()
            if remaining <= 1e-6:
                return
            self.sleeper(min(remaining, 0.01))

    def jitter(self, seconds: float) -> float:
        j = self.cfg["humanize"]["timing_jitter"]
        if j <= 0 or seconds <= 0:
            return seconds
        return seconds * self.rng.uniform(1 - j, 1 + j)

    def grab(self, region: Sequence[int]):
        return self.screen.grab(tuple(region))

    def aim(self, point: Optional[Sequence[float]] = None) -> None:
        """Move the mouse to `point` (default: click_position). Does nothing if neither is set."""
        if point is None:
            point = self.cfg["click_position"]
        if point is None:
            return
        x, y = int(round(point[0])), int(round(point[1]))
        px = int(self.cfg["humanize"]["click_jitter_px"])
        if px > 0:
            x += self.rng.randint(-px, px)
            y += self.rng.randint(-px, px)
        self.inputs.move(x, y)
        if self.cfg["wiggle_mouse"]:  # Roblox sometimes ignores clicks until the mouse has moved
            self.inputs.move(x + 1, y)
            self.inputs.move(x, y)

    def tap(self, name: str, duration: float = 0.05) -> None:
        self.inputs.down(name)
        try:
            self.sleep(duration)
        finally:
            self.inputs.up(name)

    def run_actions(self, actions) -> None:
        for action in actions:
            if "wait" in action:
                self.sleep(self.jitter(action["wait"]))
            elif "press" in action:
                if action["press"] == MOUSE:
                    self.aim()
                self.tap(action["press"], action.get("duration", 0.05))
            elif "click" in action:
                target = action["click"]
                self.aim(None if target in (None, "default") else target)
                self.tap(MOUSE, action.get("duration", 0.05))
            elif "hold" in action:
                self.tap(action["hold"], action.get("duration", 1.0))

    # ------------------------------------------------------------ phases

    def cast(self) -> None:
        c = self.cfg["cast"]
        name = c["input"]
        if name == MOUSE:
            self.aim()
        if c["release_when"]:
            det = Detector.from_config(c["release_when"])
            self.inputs.down(name)
            try:
                deadline = self.clock() + c["max_hold_seconds"]
                while self.clock() < deadline:
                    if det.present(self.grab(det.region)):
                        break
                    self.sleep(self.tick)
            finally:
                self.inputs.up(name)
        else:
            self.tap(name, max(0.05, self.jitter(c["hold_seconds"])))
        self.sleep(self.jitter(c["wait_after"]))

    def wait_for_bite(self) -> bool:
        b = self.cfg["bite"]
        if b["method"] == "wait":
            self.sleep(self.jitter(b["wait_seconds"]))
        else:
            det = Detector.from_config(b["detector"])
            deadline = self.clock() + b["timeout"]
            while not det.present(self.grab(det.region)):
                if self.clock() >= deadline:
                    return False
                self.sleep(self.tick)
            lo, hi = b["reaction_delay"]
            self.sleep(self.rng.uniform(lo, hi))
        self.run_actions(b["on_bite"])
        return True

    def reel(self) -> bool:
        """Play the reel minigame. Returns False if the minigame never showed up."""
        r = self.cfg["reel"]
        method = r["method"]
        if r["input"] == MOUSE and method != "target":
            self.aim()
        step = getattr(self, f"_step_{method}")(r)
        active = Detector.from_config(r["active_detector"]) if r["active_detector"] else None
        start = self.clock()
        seen = False
        last_seen = start
        try:
            while True:
                now = self.clock()
                own = step(now)
                presence = active.present(self.grab(active.region)) if active else own
                elapsed = now - start
                if presence is None:  # nothing to watch: just reel for a fixed time
                    if elapsed >= r["duration"]:
                        return True
                elif presence:
                    seen = True
                    last_seen = now
                elif not seen and elapsed >= r["start_timeout"]:
                    self.log("The reel minigame never showed up.")
                    return False
                elif seen and now - last_seen >= r["end_grace"]:
                    return True
                if elapsed >= r["max_seconds"]:
                    self.log(f"Reeling took over {r['max_seconds']:.0f}s - giving up on this fish.")
                    return seen or presence is None
                self.sleep(self.tick)
        finally:
            self.inputs.release_all()

    # Each _step_* gets called every frame while reeling. It returns whether the
    # minigame is visible (True/False), or None if this mode can't tell.

    def _step_spam(self, r: dict) -> StepFn:
        interval = 1.0 / r["clicks_per_second"]
        presser = Presser(self.inputs, r["input"], hold=min(0.03, interval / 2))
        next_press = [self.clock()]

        def step(now: float) -> Optional[bool]:
            presser.update(now)
            if not presser.held and now >= next_press[0]:
                presser.press(now)
                # schedule from the planned time (not "now") so loop timing doesn't slow the rate
                next_press[0] = max(next_press[0] + self.jitter(interval), now + interval / 2)
            return None

        return step

    def _step_wait(self, r: dict) -> StepFn:
        return lambda now: None  # the game reels by itself; just wait

    def _step_hold(self, r: dict) -> StepFn:
        name = r["input"]

        def step(now: float) -> Optional[bool]:
            if not self.inputs.is_held(name):
                self.inputs.down(name)
            return None

        return step

    def _step_bar(self, r: dict) -> StepFn:
        b = r["bar"]
        name = r["input"]
        region = tuple(b["region"])
        axis = "x" if b["hold_moves"] in ("right", "left") else "y"
        ctl = BarController(positive=b["hold_moves"] in ("right", "down"),
                            deadzone=b["deadzone"], lookahead=b["lookahead"])

        def step(now: float) -> Optional[bool]:
            img = self.grab(region)
            fish = find_span(color_mask(img, b["fish_color"], b["tolerance"]), axis, b["max_gap"], b["min_pixels"])
            bar = find_span(color_mask(img, b["bar_color"], b["tolerance"]), axis, b["max_gap"], b["min_pixels"])
            if fish is None and bar is None:
                if self.inputs.is_held(name):
                    self.inputs.up(name)
                return False
            hold = ctl.update(span_center(fish) if fish else None, span_center(bar) if bar else None, now)
            if hold and not self.inputs.is_held(name):
                self.inputs.down(name)
            elif not hold and self.inputs.is_held(name):
                self.inputs.up(name)
            return True

        return step

    def _step_zone(self, r: dict) -> StepFn:
        z = r["zone"]
        region = tuple(z["region"])
        axis = z["axis"]
        if axis == "auto":
            axis = "x" if region[2] >= region[3] else "y"
        trig = ZoneTrigger(margin=z["margin"], lookahead=z["lookahead"], cooldown=z["cooldown"])
        presser = Presser(self.inputs, r["input"], hold=0.03)

        def step(now: float) -> Optional[bool]:
            presser.update(now)
            img = self.grab(region)
            marker = find_span(color_mask(img, z["marker_color"], z["tolerance"]), axis, z["max_gap"], z["min_pixels"])
            target = find_span(color_mask(img, z["target_color"], z["tolerance"]), axis, z["max_gap"], z["min_pixels"])
            zone = (float(target[0]), float(target[1])) if target else None
            if trig.update(span_center(marker) if marker else None, zone, now):
                presser.press(now)
            return marker is not None or target is not None

        return step

    def _step_target(self, r: dict) -> StepFn:
        t = r["target"]
        region = tuple(t["region"])
        presser = Presser(self.inputs, MOUSE, hold=0.03)
        next_click = [float("-inf")]

        def step(now: float) -> Optional[bool]:
            presser.update(now)
            img = self.grab(region)
            mask = color_mask(img, t["color"], t["tolerance"])
            if mask.sum() < t["min_pixels"]:
                return False
            center = blob_center(mask, t["max_gap"])
            if center is None:
                return False
            if now >= next_click[0] and not presser.held:
                # On high-DPI Macs the image can be bigger than the region; scale back to screen units.
                sx = region[2] / img.shape[1]
                sy = region[3] / img.shape[0]
                self.aim((region[0] + center[0] * sx, region[1] + center[1] * sy))
                presser.press(now)
                next_click[0] = now + t["cooldown"]
            return True

        return step
