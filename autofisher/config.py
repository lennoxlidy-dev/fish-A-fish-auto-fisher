"""Loading, saving and checking config.json."""
from __future__ import annotations

import copy
import json
import os
import re
from typing import Any, Iterator, List, Tuple

MOUSE = "mouse"
BITE_METHODS = ("wait", "detect")
REEL_METHODS = ("spam", "hold", "bar", "zone", "target", "wait")
BAR_DIRECTIONS = ("right", "left", "down", "up")
ZONE_AXES = ("auto", "x", "y")

# Everything the macro can be told. config.json only needs the parts you change.
DEFAULTS: dict = {
    "hotkeys": {"toggle": "f6", "quit": "f7", "capture": "f8"},
    "start_paused": True,
    "require_roblox_focus": True,
    "click_position": None,
    "wiggle_mouse": True,
    "loop_hz": 100,
    "cast": {
        "input": MOUSE,
        "hold_seconds": 0.0,
        "release_when": None,
        "max_hold_seconds": 3.0,
        "wait_after": 0.5,
    },
    "bite": {
        "method": "wait",
        "wait_seconds": 3.0,
        "detector": None,
        "timeout": 30.0,
        "reaction_delay": [0.05, 0.15],
        "on_bite": [],
        "on_timeout": [],
    },
    "reel": {
        "method": "spam",
        "input": MOUSE,
        "clicks_per_second": 12,
        "duration": 8.0,
        "active_detector": None,
        "start_timeout": 3.0,
        "end_grace": 0.6,
        "max_seconds": 90.0,
        "bar": {
            "region": None,
            "hold_moves": "right",
            "fish_color": None,
            "bar_color": None,
            "tolerance": 30,
            "min_pixels": 4,
            "max_gap": 20,
            "deadzone": 4.0,
            "lookahead": 0.15,
        },
        "zone": {
            "region": None,
            "axis": "auto",
            "marker_color": None,
            "target_color": None,
            "tolerance": 30,
            "min_pixels": 3,
            "max_gap": 12,
            "margin": 2.0,
            "lookahead": 0.03,
            "cooldown": 0.3,
        },
        "target": {
            "region": None,
            "color": None,
            "tolerance": 30,
            "min_pixels": 30,
            "max_gap": 4,
            "cooldown": 0.2,
        },
    },
    "after_catch": {"actions": [], "wait": 1.0},
    "auto_sell": {"enabled": False, "every": 50, "actions": []},
    "humanize": {"timing_jitter": 0.1, "click_jitter_px": 2},
}


class ConfigError(Exception):
    def __init__(self, problems: List[str]):
        self.problems = problems
        super().__init__("config problems:\n  - " + "\n  - ".join(problems))


# ---------------------------------------------------------------- load / save

def deep_merge(base: dict, override: dict, unknown: List[str], path: str = "") -> dict:
    """Return base with override applied on top. Keys starting with "_" are comments."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key.startswith("_"):
            continue
        if key not in base:
            unknown.append(path + key)
            continue
        if isinstance(base[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(base[key], value, unknown, path + key + ".")
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_config(path: str) -> Tuple[dict, List[str]]:
    """Load config.json on top of DEFAULTS. Returns (config, warnings). Raises ConfigError."""
    warnings: List[str] = []
    if not os.path.exists(path):
        warnings.append(f"{path} not found - using the built-in defaults "
                        "(click to cast, wait, spam-click). Run setup to teach it the game.")
        return copy.deepcopy(DEFAULTS), warnings
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError([f"{path} is not valid JSON: {e.msg} (line {e.lineno}, column {e.colno})"])
    if not isinstance(data, dict):
        raise ConfigError([f"{path} must contain a JSON object {{ ... }}"])
    unknown: List[str] = []
    cfg = deep_merge(DEFAULTS, data, unknown)
    for key in unknown:
        warnings.append(f"unknown setting '{key}' in {path} was ignored (typo?)")
    problems = validate(cfg)
    if problems:
        raise ConfigError(problems)
    return cfg, warnings


def dumps(cfg: dict) -> str:
    text = json.dumps(cfg, indent=2)
    # Keep short number lists like [12, 34, 56] on one line so the file stays readable.
    return re.sub(r"\[\s+([-\d.,\s]+?)\s+\]",
                  lambda m: "[" + ", ".join(p.strip() for p in m.group(1).split(",")) + "]",
                  text)


def save_config(cfg: dict, path: str) -> None:
    if os.path.exists(path):
        backup = path + ".bak"
        if os.path.exists(backup):
            os.remove(backup)
        os.rename(path, backup)
    with open(path, "w", encoding="utf-8") as f:
        f.write(dumps(cfg) + "\n")


# ---------------------------------------------------------------- validation

def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


class _Checker:
    def __init__(self) -> None:
        self.problems: List[str] = []

    def add(self, msg: str) -> None:
        self.problems.append(msg)

    def number(self, path: str, v: Any, lo: float = None, hi: float = None) -> None:
        if not _is_num(v):
            self.add(f"{path} must be a number (got {v!r})")
        elif lo is not None and v < lo:
            self.add(f"{path} must be at least {lo} (got {v})")
        elif hi is not None and v > hi:
            self.add(f"{path} must be at most {hi} (got {v})")

    def boolean(self, path: str, v: Any) -> None:
        if not isinstance(v, bool):
            self.add(f"{path} must be true or false (got {v!r})")

    def choice(self, path: str, v: Any, options: Tuple[str, ...]) -> None:
        if v not in options:
            self.add(f"{path} must be one of {', '.join(repr(o) for o in options)} (got {v!r})")

    def point(self, path: str, v: Any) -> None:
        if not (isinstance(v, list) and len(v) == 2 and all(_is_int(n) for n in v)):
            self.add(f"{path} must be [x, y] (got {v!r})")

    def region(self, path: str, v: Any) -> None:
        if not (isinstance(v, list) and len(v) == 4 and all(_is_int(n) for n in v) and v[2] > 0 and v[3] > 0):
            self.add(f"{path} must be [x, y, width, height] with a positive width and height (got {v!r})")

    def color(self, path: str, v: Any) -> None:
        colors = v if (isinstance(v, list) and v and isinstance(v[0], list)) else [v]
        for c in colors:
            if not (isinstance(c, list) and len(c) == 3 and all(_is_int(n) and 0 <= n <= 255 for n in c)):
                self.add(f"{path} must be an [R, G, B] color (0-255 each) or a list of them (got {v!r})")
                return

    def input_name(self, path: str, v: Any) -> None:
        if not isinstance(v, str) or not v.strip() or v != v.strip().lower():
            self.add(f'{path} must be "mouse" or a lowercase key name like "e" or "space" (got {v!r})')

    def detector(self, path: str, d: Any) -> None:
        if not isinstance(d, dict):
            self.add(f"{path} must be an object with region and color (got {d!r})")
            return
        allowed = {"region", "color", "tolerance", "min_pixels", "invert"}
        for key in d:
            if key not in allowed and not key.startswith("_"):
                self.add(f"{path}.{key} is not a detector setting (allowed: {', '.join(sorted(allowed))})")
        if "region" not in d:
            self.add(f"{path}.region is missing")
        else:
            self.region(f"{path}.region", d["region"])
        if "color" not in d:
            self.add(f"{path}.color is missing")
        else:
            self.color(f"{path}.color", d["color"])
        if "tolerance" in d:
            self.number(f"{path}.tolerance", d["tolerance"], 0, 255)
        if "min_pixels" in d:
            self.number(f"{path}.min_pixels", d["min_pixels"], 1)
        if "invert" in d:
            self.boolean(f"{path}.invert", d["invert"])

    def actions(self, path: str, actions: Any) -> None:
        if not isinstance(actions, list):
            self.add(f"{path} must be a list of steps (got {actions!r})")
            return
        kinds = ("press", "click", "wait", "hold")
        for i, a in enumerate(actions):
            p = f"{path}[{i}]"
            if not isinstance(a, dict):
                self.add(f"{p} must be an object like {{\"press\": \"e\"}} (got {a!r})")
                continue
            found = [k for k in kinds if k in a]
            if len(found) != 1:
                self.add(f"{p} must have exactly one of {', '.join(kinds)} (got {a!r})")
                continue
            kind = found[0]
            extra = set(a) - {kind, "duration"}
            if extra:
                self.add(f"{p} has unknown keys {sorted(extra)}")
            if kind in ("press", "hold"):
                self.input_name(f"{p}.{kind}", a[kind])
            elif kind == "click":
                if a["click"] not in (None, "default"):
                    self.point(f"{p}.click", a["click"])
            elif kind == "wait":
                self.number(f"{p}.wait", a["wait"], 0)
            if "duration" in a:
                self.number(f"{p}.duration", a["duration"], 0)


def validate(cfg: dict) -> List[str]:
    c = _Checker()

    hk = cfg["hotkeys"]
    for name in ("toggle", "quit", "capture"):
        if not isinstance(hk.get(name), str) or not hk.get(name):
            c.add(f"hotkeys.{name} must be a key name like \"f6\"")
    names = [str(hk.get(n, "")).lower() for n in ("toggle", "quit", "capture")]
    if len(set(names)) != 3:
        c.add("hotkeys.toggle, hotkeys.quit and hotkeys.capture must all be different keys")

    c.boolean("start_paused", cfg["start_paused"])
    c.boolean("require_roblox_focus", cfg["require_roblox_focus"])
    c.boolean("wiggle_mouse", cfg["wiggle_mouse"])
    if cfg["click_position"] is not None:
        c.point("click_position", cfg["click_position"])
    c.number("loop_hz", cfg["loop_hz"], 10, 500)

    cast = cfg["cast"]
    c.input_name("cast.input", cast["input"])
    c.number("cast.hold_seconds", cast["hold_seconds"], 0)
    c.number("cast.max_hold_seconds", cast["max_hold_seconds"], 0)
    c.number("cast.wait_after", cast["wait_after"], 0)
    if cast["release_when"] is not None:
        c.detector("cast.release_when", cast["release_when"])

    bite = cfg["bite"]
    c.choice("bite.method", bite["method"], BITE_METHODS)
    c.number("bite.wait_seconds", bite["wait_seconds"], 0)
    c.number("bite.timeout", bite["timeout"], 0.1)
    rd = bite["reaction_delay"]
    if not (isinstance(rd, list) and len(rd) == 2 and all(_is_num(v) and v >= 0 for v in rd) and rd[0] <= rd[1]):
        c.add(f"bite.reaction_delay must be [min_seconds, max_seconds] (got {rd!r})")
    if bite["method"] == "detect":
        if bite["detector"] is None:
            c.add('bite.detector is required when bite.method is "detect" (run setup, or use "wait")')
        else:
            c.detector("bite.detector", bite["detector"])
    c.actions("bite.on_bite", bite["on_bite"])
    c.actions("bite.on_timeout", bite["on_timeout"])

    reel = cfg["reel"]
    c.choice("reel.method", reel["method"], REEL_METHODS)
    c.input_name("reel.input", reel["input"])
    c.number("reel.clicks_per_second", reel["clicks_per_second"], 1, 40)
    c.number("reel.duration", reel["duration"], 0)
    c.number("reel.start_timeout", reel["start_timeout"], 0)
    c.number("reel.end_grace", reel["end_grace"], 0)
    c.number("reel.max_seconds", reel["max_seconds"], 1)
    if reel["active_detector"] is not None:
        c.detector("reel.active_detector", reel["active_detector"])

    method = reel["method"]
    if method == "bar":
        b = reel["bar"]
        for key in ("region", "fish_color", "bar_color"):
            if b[key] is None:
                c.add(f'reel.bar.{key} is required when reel.method is "bar" (run setup)')
        if b["region"] is not None:
            c.region("reel.bar.region", b["region"])
        for key in ("fish_color", "bar_color"):
            if b[key] is not None:
                c.color(f"reel.bar.{key}", b[key])
        c.choice("reel.bar.hold_moves", b["hold_moves"], BAR_DIRECTIONS)
        c.number("reel.bar.tolerance", b["tolerance"], 0, 255)
        c.number("reel.bar.min_pixels", b["min_pixels"], 1)
        c.number("reel.bar.max_gap", b["max_gap"], 0)
        c.number("reel.bar.deadzone", b["deadzone"], 0)
        c.number("reel.bar.lookahead", b["lookahead"], 0, 1)
    elif method == "zone":
        z = reel["zone"]
        for key in ("region", "marker_color", "target_color"):
            if z[key] is None:
                c.add(f'reel.zone.{key} is required when reel.method is "zone" (run setup)')
        if z["region"] is not None:
            c.region("reel.zone.region", z["region"])
        for key in ("marker_color", "target_color"):
            if z[key] is not None:
                c.color(f"reel.zone.{key}", z[key])
        c.choice("reel.zone.axis", z["axis"], ZONE_AXES)
        c.number("reel.zone.tolerance", z["tolerance"], 0, 255)
        c.number("reel.zone.min_pixels", z["min_pixels"], 1)
        c.number("reel.zone.max_gap", z["max_gap"], 0)
        c.number("reel.zone.margin", z["margin"], 0)
        c.number("reel.zone.lookahead", z["lookahead"], 0, 1)
        c.number("reel.zone.cooldown", z["cooldown"], 0)
    elif method == "target":
        t = reel["target"]
        for key in ("region", "color"):
            if t[key] is None:
                c.add(f'reel.target.{key} is required when reel.method is "target" (run setup)')
        if t["region"] is not None:
            c.region("reel.target.region", t["region"])
        if t["color"] is not None:
            c.color("reel.target.color", t["color"])
        c.number("reel.target.tolerance", t["tolerance"], 0, 255)
        c.number("reel.target.min_pixels", t["min_pixels"], 1)
        c.number("reel.target.max_gap", t["max_gap"], 0)
        c.number("reel.target.cooldown", t["cooldown"], 0)

    c.actions("after_catch.actions", cfg["after_catch"]["actions"])
    c.number("after_catch.wait", cfg["after_catch"]["wait"], 0)

    sell = cfg["auto_sell"]
    c.boolean("auto_sell.enabled", sell["enabled"])
    c.number("auto_sell.every", sell["every"], 1)
    c.actions("auto_sell.actions", sell["actions"])
    if sell["enabled"] is True and not sell["actions"]:
        c.add("auto_sell.enabled is true but auto_sell.actions is empty - add the steps to sell")

    hum = cfg["humanize"]
    c.number("humanize.timing_jitter", hum["timing_jitter"], 0, 0.5)
    c.number("humanize.click_jitter_px", hum["click_jitter_px"], 0, 50)

    # The macro must never "press" one of its own hotkeys.
    hotkeys = set(names)
    for path, key in iter_key_inputs(cfg):
        if key in hotkeys:
            c.add(f"{path} uses {key!r}, which is also a hotkey - pick a different key")
    return c.problems


def iter_key_inputs(cfg: dict) -> Iterator[Tuple[str, str]]:
    """Yield (setting path, key name) for every keyboard key the macro may press."""
    def from_actions(path: str, actions: Any) -> Iterator[Tuple[str, str]]:
        if not isinstance(actions, list):
            return
        for i, a in enumerate(actions):
            if isinstance(a, dict):
                for kind in ("press", "hold"):
                    if isinstance(a.get(kind), str):
                        yield f"{path}[{i}].{kind}", a[kind]

    for path, value in (("cast.input", cfg["cast"]["input"]), ("reel.input", cfg["reel"]["input"])):
        if isinstance(value, str) and value != MOUSE:
            yield path, value
    yield from from_actions("bite.on_bite", cfg["bite"]["on_bite"])
    yield from from_actions("bite.on_timeout", cfg["bite"]["on_timeout"])
    yield from from_actions("after_catch.actions", cfg["after_catch"]["actions"])
    yield from from_actions("auto_sell.actions", cfg["auto_sell"]["actions"])
