"""Command line: python fisher.py [run|setup|picker|check]"""
from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

from .config import MOUSE, ConfigError, iter_key_inputs, load_config, save_config, validate
from .platform_utils import enable_dpi_awareness, enable_high_res_timer, roblox_focused

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG = os.path.join(PROJECT_DIR, "config.json")


def _load(path: str) -> Optional[dict]:
    try:
        cfg, warnings = load_config(path)
    except ConfigError as e:
        print(f"There's a problem with {path}:")
        for p in e.problems:
            print(f"  - {p}")
        print("Fix it in a text editor, or run setup again.")
        return None
    for w in warnings:
        print(f"Note: {w}")
    return cfg


def _bad_keys(cfg: dict, inputs) -> List[str]:
    return [f"{path}: unknown key name {key!r}" for path, key in iter_key_inputs(cfg)
            if not inputs.validate_key(key)]


def _describe(cfg: dict) -> str:
    cast = cfg["cast"]
    how = "click" if cast["input"] == MOUSE else f"key '{cast['input']}'"
    if cast["release_when"]:
        cast_txt = f"hold {how} until the power bar is ready"
    elif cast["hold_seconds"] > 0:
        cast_txt = f"hold {how} for {cast['hold_seconds']}s"
    else:
        cast_txt = how
    bite = cfg["bite"]
    bite_txt = (f"wait {bite['wait_seconds']}s" if bite["method"] == "wait"
                else "watch the screen" + (" (for something to disappear)" if bite["detector"].get("invert") else ""))
    reel = cfg["reel"]
    reel_txt = {
        "spam": f"spam {'click' if reel['input'] == MOUSE else reel['input']} at {reel['clicks_per_second']}/s",
        "hold": f"hold {'mouse' if reel['input'] == MOUSE else reel['input']}",
        "bar": "keep the fish in the bar",
        "zone": "hit the target zone",
        "target": "click pop-ups",
        "wait": "wait",
    }[reel["method"]]
    if reel["method"] in ("spam", "hold", "wait"):
        reel_txt += " until the reel screen closes" if reel["active_detector"] else f" for {reel['duration']}s"
    sell = cfg["auto_sell"]
    sell_txt = f" | sell every {sell['every']}" if sell["enabled"] else ""
    return f"cast: {cast_txt} | bite: {bite_txt} | reel: {reel_txt}{sell_txt}"


def cmd_run(config_path: str) -> int:
    cfg = _load(config_path)
    if cfg is None:
        return 1
    from .bot import FishingBot
    from .controls import Controls, HotkeyListener
    from .inputs import create_input_backend
    from .screen import MssScreen

    inputs = create_input_backend()
    bad = _bad_keys(cfg, inputs)
    if bad:
        print("Some key names in the config aren't recognised:")
        for b in bad:
            print(f"  - {b}")
        return 1
    screen = MssScreen()
    controls = Controls(start_paused=cfg["start_paused"])
    hk = cfg["hotkeys"]
    listener = HotkeyListener({hk["toggle"]: controls.toggle, hk["quit"]: controls.request_quit}).start()
    focus = roblox_focused if (cfg["require_roblox_focus"] and sys.platform == "win32") else None
    bot = FishingBot(cfg, screen, inputs, controls, focus_check=focus)

    print("=" * 64)
    print(" Fish A Fish auto fisher")
    print("=" * 64)
    print(_describe(cfg))
    print(f"  {hk['toggle'].upper()} = start / pause    {hk['quit'].upper()} = quit    "
          "mouse to the top-left corner = emergency pause")
    if cfg["start_paused"]:
        print(f"Click on the Roblox window, then press {hk['toggle'].upper()} to start.")
    try:
        bot.run()
    except KeyboardInterrupt:
        pass
    finally:
        inputs.release_all()
        listener.stop()
        s = bot.stats
        print(f"Done. reels: {s.reels}, missed: {s.missed}, no bite: {s.no_bites}")
    return 0


def cmd_setup(config_path: str) -> int:
    from .controls import HotkeyListener
    from .inputs import create_input_backend
    from .screen import MssScreen
    from .wizard import Wizard

    inputs = create_input_backend()
    screen = MssScreen()
    wizard = Wizard(screen, inputs, capture_key="f8")
    listener = HotkeyListener({"f8": wizard.on_capture_key}).start()
    try:
        cfg = wizard.run()
    except (KeyboardInterrupt, EOFError):
        print("\nSetup cancelled - nothing was saved.")
        return 1
    finally:
        listener.stop()
    problems = validate(cfg) + _bad_keys(cfg, inputs)
    save_config(cfg, config_path)
    print(f"Saved to {config_path}" + (" (old one kept as config.json.bak)"
                                       if os.path.exists(config_path + ".bak") else ""))
    if problems:
        print("But a few things need fixing (edit config.json or run setup again):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(_describe(cfg))
    print("\nNext: run 'run.bat' (or: python fisher.py), click on Roblox and press F6.")
    print("Tip: 'python fisher.py check' shows live what the macro sees on screen.")
    return 0


def cmd_picker(config_path: str) -> int:
    from .inputs import create_input_backend
    from .screen import MssScreen
    from .tools import run_picker

    cfg = _load(config_path)
    key = cfg["hotkeys"]["capture"] if cfg else "f8"
    run_picker(MssScreen(), create_input_backend(), key)
    return 0


def cmd_check(config_path: str) -> int:
    from .screen import MssScreen
    from .tools import run_check

    cfg = _load(config_path)
    if cfg is None:
        return 1
    run_check(cfg, MssScreen(), os.path.join(PROJECT_DIR, "debug"))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fisher.py",
        description="Screen-reading auto fisher for the Roblox game Fish A Fish.",
        epilog="commands:\n"
               "  run     start the macro (default)\n"
               "  setup   answer a few questions so the macro learns the game\n"
               "  picker  show the mouse position and the colour under it, live\n"
               "  check   show live what the macro's screen detection sees",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("command", nargs="?", default="run", choices=["run", "setup", "picker", "check"])
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="config file (default: config.json)")
    args = parser.parse_args(argv)

    enable_dpi_awareness()
    enable_high_res_timer()
    commands = {"run": cmd_run, "setup": cmd_setup, "picker": cmd_picker, "check": cmd_check}
    return commands[args.command](args.config)
