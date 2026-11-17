"""Interactive setup: teaches the macro what Fish A Fish looks like on *your* screen.

Questions are answered in the terminal. Whenever the wizard needs a spot or a
colour from the game, you hover the mouse over it in Roblox and press the
capture key (F8 by default).
"""
from __future__ import annotations

import copy
import queue
import time
from typing import Callable, List, Optional, Sequence, Tuple

from .config import DEFAULTS, MOUSE
from .vision import Detector

Capture = Tuple[int, int, Tuple[int, int, int]]  # x, y, (r, g, b)


class Wizard:
    def __init__(self, screen, inputs, capture_key: str = "f8",
                 input_fn: Callable[[str], str] = input,
                 out: Callable[[str], None] = print,
                 capture_fn: Optional[Callable[[], Capture]] = None,
                 pause: Callable[[float], None] = time.sleep) -> None:
        self.screen = screen
        self.inputs = inputs
        self.key = capture_key.upper()
        self.input_fn = input_fn
        self.out = out
        self.pause = pause
        self._queue: "queue.Queue[Capture]" = queue.Queue()
        self._capture_fn = capture_fn or self._wait_for_hotkey

    # ------------------------------------------------------------ hotkey plumbing

    def on_capture_key(self) -> None:
        """Hotkey callback: remember where the mouse is and the colour under it."""
        pos = self.inputs.position()
        if pos is None:
            return
        try:
            rgb = self.screen.pixel(*pos)
        except Exception:
            rgb = (0, 0, 0)
        self._queue.put((pos[0], pos[1], rgb))

    def _wait_for_hotkey(self) -> Capture:
        while not self._queue.empty():  # forget presses from before the question was asked
            self._queue.get_nowait()
        while True:
            try:
                return self._queue.get(timeout=0.2)  # timeout keeps Ctrl+C working on Windows
            except queue.Empty:
                continue

    # ------------------------------------------------------------ terminal questions

    def ask(self, question: str, default: Optional[str] = None) -> str:
        suffix = f" [{default}]" if default not in (None, "") else ""
        answer = self.input_fn(f"{question}{suffix}: ").strip()
        return answer if answer else (default or "")

    def ask_choice(self, question: str, options: Sequence[Tuple[str, str]], default: int = 1) -> str:
        self.out("")
        self.out(question)
        for i, (_value, label) in enumerate(options, 1):
            self.out(f"  {i}) {label}")
        while True:
            answer = self.ask("Type a number", str(default))
            if answer.isdigit() and 1 <= int(answer) <= len(options):
                return options[int(answer) - 1][0]
            self.out(f"  Please type a number from 1 to {len(options)}.")

    def ask_yes_no(self, question: str, default: bool = False) -> bool:
        while True:
            answer = self.ask(f"{question} (y/n)", "y" if default else "n").lower()
            if answer in ("y", "yes"):
                return True
            if answer in ("n", "no"):
                return False
            self.out("  Please answer y or n.")

    def ask_number(self, question: str, default: float, minimum: float = 0.0,
                   integer: bool = False) -> float:
        while True:
            answer = self.ask(question, str(default))
            try:
                value = int(answer) if integer else float(answer)
            except ValueError:
                self.out("  Please type a number.")
                continue
            if value < minimum:
                self.out(f"  Please type a number of at least {minimum}.")
                continue
            return value

    def ask_key(self, question: str, default: str) -> str:
        while True:
            key = self.ask(question, default).lower()
            if key == MOUSE:
                self.out("  That's the mouse - please type a keyboard key name.")
                continue
            if self.inputs.validate_key(key):
                return key
            self.out("  Unknown key name. Examples: e, f, space, enter, shift, 1, tab")

    def ask_input(self, what: str, default: str = MOUSE) -> str:
        """Mouse or a keyboard key?"""
        choice = self.ask_choice(f"Do you {what} with the mouse or with a key?",
                                 [(MOUSE, "Left mouse button"), ("key", "A keyboard key")],
                                 1 if default == MOUSE else 2)
        if choice == MOUSE:
            return MOUSE
        return self.ask_key("Which key? (e.g. e, f, space)", "e" if default == MOUSE else default)

    # ------------------------------------------------------------ captures

    def capture(self, instruction: str) -> Capture:
        self.out(f"  -> {instruction}")
        self.out(f"     Then press {self.key} (while the Roblox window is active).")
        x, y, rgb = self._capture_fn()
        self.out(f"     Got it: position [{x}, {y}], color [{rgb[0]}, {rgb[1]}, {rgb[2]}]")
        return x, y, rgb

    def capture_point(self, instruction: str) -> List[int]:
        x, y, _ = self.capture(instruction)
        return [x, y]

    def capture_region(self, what: str) -> List[int]:
        self.out(f"  Now mark a box around {what}. Make it a bit bigger than the thing itself.")
        x1, y1, _ = self.capture("Hover over the TOP-LEFT corner of the box.")
        x2, y2, _ = self.capture("Hover over the BOTTOM-RIGHT corner of the box.")
        x, y = min(x1, x2), min(y1, y2)
        w, h = abs(x2 - x1) + 1, abs(y2 - y1) + 1
        if w < 5 or h < 5:
            self.out("     That box is very small - making it a little bigger.")
            x, y, w, h = x - max(0, (5 - w) // 2), y - max(0, (5 - h) // 2), max(w, 5), max(h, 5)
        self.out(f"     Box: [{x}, {y}, {w}, {h}] (x, y, width, height)")
        return [x, y, w, h]

    def capture_colors(self, what: str) -> List[List[int]]:
        colors = []
        _, _, rgb = self.capture(f"Hover EXACTLY over {what} (a solid part, not an edge).")
        colors.append(list(rgb))
        while self.ask_yes_no("Add another color sample for it? (helps if it flashes or has "
                              "several shades)", False):
            _, _, rgb = self.capture(f"Hover over another part/shade of {what}.")
            colors.append(list(rgb))
        return colors

    def count_now(self, det: dict) -> int:
        d = Detector.from_config(det)
        return d.count(self.screen.grab(d.region))

    def build_detector(self, thing: str, appears: bool = True) -> dict:
        """Region + colour(s), then tune min_pixels by measuring 'visible' vs 'gone'."""
        self.out(f"\n  Get {thing} to show up in the game (it's fine to redo a cast).")
        region = self.capture_region(thing)
        colors = self.capture_colors(thing)
        det = {"region": region, "color": colors[0] if len(colors) == 1 else colors,
               "tolerance": 30, "min_pixels": 10, "invert": not appears}
        visible = self.count_now(det)
        self.out(f"     {visible} matching pixels right now (while it's visible).")
        self.capture(f"Now wait until {thing} is GONE (not on screen), hover anywhere")
        gone = self.count_now(det)
        self.out(f"     {gone} matching pixels while it's gone.")
        if visible > gone:
            det["min_pixels"] = max(1, gone + max(1, (visible - gone) // 3))
            self.out(f"     Using min_pixels = {det['min_pixels']}. Looks good!")
        else:
            det["min_pixels"] = max(5, visible // 2)
            self.out("     !! It looked the same visible and gone. Re-run setup and pick a more")
            self.out("        unique colour or a tighter box, or tweak it later with:  python fisher.py check")
        return det

    # ------------------------------------------------------------ the wizard itself

    def run(self) -> dict:
        cfg = copy.deepcopy(DEFAULTS)
        o = self.out
        o("=" * 64)
        o(" Fish A Fish auto fisher - setup")
        o("=" * 64)
        o("Put Roblox where you'll play it (fullscreen is easiest) and don't move")
        o("or resize it afterwards - the macro remembers screen positions.")
        o(f"Answer questions here; when asked to capture, switch to Roblox, hover")
        o(f"the mouse over the thing and press {self.key}.")

        # 1. where to click
        o("\n--- Step 1/6: where to click ---")
        if self.ask_yes_no("Move the mouse to a fixed spot before clicking? (recommended)", True):
            cfg["click_position"] = self.capture_point(
                "Hover over the spot you click to cast (e.g. the middle of the water).")

        # 2. casting
        o("\n--- Step 2/6: casting ---")
        cast = cfg["cast"]
        style = self.ask_choice("How do you cast your line?", [
            ("click", "Click once"),
            ("hold", "Hold the mouse for a while (power/charge bar), then let go"),
            ("key", "Press a key once"),
            ("holdkey", "Hold a key for a while, then let go"),
        ])
        cast["input"] = MOUSE if style in ("click", "hold") else self.ask_key("Which key?", "e")
        if style in ("hold", "holdkey"):
            how = self.ask_choice("When should it let go?", [
                ("time", "After a fixed time"),
                ("detect", "When something appears (e.g. the power bar turns green / is full)"),
            ])
            if how == "time":
                cast["hold_seconds"] = self.ask_number("Hold for how many seconds?", 1.0, 0.05)
            else:
                cast["release_when"] = self.build_detector("the full/green part of the power bar")
                cast["max_hold_seconds"] = self.ask_number("Never hold longer than (seconds)", 3.0, 0.1)
        cast["wait_after"] = self.ask_number(
            "Seconds to wait after casting before looking for a bite", 0.5, 0.0)

        # 3. bite
        o("\n--- Step 3/6: knowing when a fish bites ---")
        bite = cfg["bite"]
        how = self.ask_choice("How can you tell a fish is biting?", [
            ("wait", "I can't really / it doesn't matter - just wait a few seconds"),
            ("appear", "Something APPEARS (a '!' mark, 'Click!' text, a popup, the reel minigame...)"),
            ("disappear", "Something DISAPPEARS (e.g. the bobber goes under water)"),
        ])
        if how == "wait":
            bite["method"] = "wait"
            bite["wait_seconds"] = self.ask_number("Wait how many seconds after casting?", 3.0, 0.0)
        else:
            bite["method"] = "detect"
            thing = self.ask("In a few words, what appears/disappears?",
                             "the bite indicator" if how == "appear" else "the bobber")
            bite["detector"] = self.build_detector(thing, appears=(how == "appear"))
            bite["timeout"] = self.ask_number("Recast if nothing bites within (seconds)", 30.0, 1.0)
        if self.ask_yes_no("When a fish bites, do you have to click or press a key to hook it?", False):
            hook = self.ask_input("hook the fish")
            bite["on_bite"] = [{"click": "default"}] if hook == MOUSE else [{"press": hook}]

        # 4. reeling
        o("\n--- Step 4/6: reeling it in ---")
        reel = cfg["reel"]
        method = self.ask_choice("What do you do to reel the fish in?", [
            ("spam", "Click (or press a key) as fast as I can"),
            ("hold", "Hold the mouse (or a key) down"),
            ("bar", "Keep a fish/marker inside my bar by holding and letting go"),
            ("zone", "Click when a moving marker is inside a target zone"),
            ("target", "Click on things that pop up on screen"),
            ("none", "Nothing - it catches by itself"),
        ])
        if method == "none":
            reel["method"] = "wait"
            reel["duration"] = self.ask_number("How many seconds until the fish is caught?", 3.0, 0.0)
        elif method in ("spam", "hold"):
            reel["method"] = method
            reel["input"] = self.ask_input("reel")
            if method == "spam":
                reel["clicks_per_second"] = self.ask_number("Clicks per second", 12, 1, integer=True)
            end = self.ask_choice("How should the macro know reeling is finished?", [
                ("time", "After a fixed number of seconds"),
                ("detect", "When part of the reel screen (like a progress bar) disappears"),
            ])
            if end == "time":
                reel["duration"] = self.ask_number("Reel for how many seconds?", 8.0, 0.1)
            else:
                reel["active_detector"] = self.build_detector(
                    "a part of the reel screen that's ONLY visible while reeling (e.g. the progress bar)")
        elif method == "bar":
            reel["method"] = "bar"
            reel["input"] = self.ask_input("move your bar")
            b = reel["bar"]
            o("\n  Start reeling a fish so the bar minigame is on screen. If the fish gets")
            o("  away while you do this, just cast again and carry on.")
            b["region"] = self.capture_region("the whole bar track (where both the fish and your bar move)")
            b["fish_color"] = _one_or_many(self.capture_colors("the FISH / marker you have to follow"))
            b["bar_color"] = _one_or_many(self.capture_colors("YOUR BAR (a part not covered by the fish)"))
            b["hold_moves"] = self.ask_choice("When you hold, which way does your bar move?", [
                ("right", "Right"), ("left", "Left"), ("up", "Up"), ("down", "Down")])
        elif method == "zone":
            reel["method"] = "zone"
            reel["input"] = self.ask_input("hit the zone")
            z = reel["zone"]
            o("\n  Start reeling so the moving marker and the target zone are on screen.")
            z["region"] = self.capture_region("the whole track the marker moves along")
            z["marker_color"] = _one_or_many(self.capture_colors("the MOVING marker/needle"))
            z["target_color"] = _one_or_many(self.capture_colors("the TARGET zone (where you should click)"))
        elif method == "target":
            reel["method"] = "target"
            t = reel["target"]
            o("\n  Start reeling so the things you click on show up.")
            t["region"] = self.capture_region("the area where they can pop up")
            t["color"] = _one_or_many(self.capture_colors("one of the things you click"))
        if method in ("bar", "zone", "target"):
            reel["end_grace"] = 1.0 if method == "target" else 0.6

        # 5. after a catch
        o("\n--- Step 5/6: after a catch ---")
        after = cfg["after_catch"]
        what = self.ask_choice("Is there a popup or anything you must close after catching a fish?", [
            ("none", "No"),
            ("key", "Yes - I press a key"),
            ("click", "Yes - I click a button"),
        ])
        if what == "key":
            after["actions"] = [{"press": self.ask_key("Which key?", "e")}]
        elif what == "click":
            after["actions"] = [{"click": self.capture_point(
                "Catch a fish, then hover over the button you click to close the popup.")}]
        after["wait"] = self.ask_number("Seconds to wait before casting again", 1.0, 0.0)

        # 6. auto sell
        o("\n--- Step 6/6: auto sell (optional) ---")
        sell = cfg["auto_sell"]
        if self.ask_yes_no("Do you want it to sell automatically every so often?", False):
            sell["every"] = self.ask_number("Sell after how many catches?", 50, 1, integer=True)
            sell["actions"] = self.record_actions()
            sell["enabled"] = bool(sell["actions"])

        # Hotkeys stay at the defaults; make sure no chosen key collides with them.
        o("\nSetup finished!")
        return cfg

    def record_actions(self) -> List[dict]:
        o = self.out
        o("Tell me the steps to sell, one at a time:")
        o("  key <name>    press a key            (e.g.  key g)")
        o("  click         click a spot           (you'll capture it in the game)")
        o("  wait <secs>   wait                   (e.g.  wait 1.5)")
        o("  done          finished")
        actions: List[dict] = []
        while True:
            line = self.ask("step", "done").strip().lower()
            parts = line.split()
            if not parts or parts[0] == "done":
                return actions
            if parts[0] == "key" and len(parts) == 2 and self.inputs.validate_key(parts[1]):
                actions.append({"press": parts[1]})
            elif parts[0] == "click" and len(parts) == 1:
                actions.append({"click": self.capture_point("Hover over the spot to click.")})
            elif parts[0] == "wait" and len(parts) == 2 and _is_float(parts[1]) and float(parts[1]) >= 0:
                actions.append({"wait": float(parts[1])})
            else:
                o("  Didn't understand that. Examples: key g | click | wait 1.5 | done")
                continue
            o(f"  added: {actions[-1]}")


def _one_or_many(colors: List[List[int]]):
    return colors[0] if len(colors) == 1 else colors


def _is_float(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False
