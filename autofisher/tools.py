"""Helper tools: `picker` (live mouse position + colour) and `check` (live detector readout)."""
from __future__ import annotations

import os
import queue
import time
from typing import Callable, List, Tuple

import numpy as np

from .controls import HotkeyListener
from .vision import Detector, blob_center, color_mask, draw_rect, find_span, span_center, write_png


def run_picker(screen, inputs, capture_key: str = "f8") -> None:
    saved: "queue.Queue[bool]" = queue.Queue()
    listener = HotkeyListener({capture_key: lambda: saved.put(True)}).start()
    print("Move the mouse over the game. Its position and the colour under it are shown live.")
    print(f"Press {capture_key.upper()} to keep a line, Ctrl+C to exit.\n")
    try:
        while True:
            pos = inputs.position()
            try:
                rgb = screen.pixel(*pos) if pos else None
            except Exception:
                rgb = None
            rgb_text = f"[{rgb[0]:3d}, {rgb[1]:3d}, {rgb[2]:3d}]" if rgb else "[?, ?, ?]"
            line = f"position [{pos[0]:5d}, {pos[1]:5d}]   color {rgb_text}" if pos else "position unknown"
            if not saved.empty():
                saved.get()
                print("\r" + line + "   <- saved")
            else:
                print("\r" + line + "          ", end="", flush=True)
            time.sleep(0.1)
    except KeyboardInterrupt:
        print()
    finally:
        listener.stop()


Probe = Tuple[str, List[int], Callable[[np.ndarray], str], Callable[[np.ndarray], List[Tuple[np.ndarray, Tuple[int, int, int]]]]]


def _detector_probe(label: str, d: dict) -> Probe:
    det = Detector.from_config(d)

    def describe(img: np.ndarray) -> str:
        n = det.count(img)
        state = "YES" if det.present(img) else "no"
        extra = ", inverted" if det.invert else ""
        return f"{label}: {n}px (need {det.min_pixels}{extra}) -> {state}"

    def masks(img: np.ndarray):
        return [(color_mask(img, det.colors, det.tolerance), (255, 0, 255))]

    return label, list(det.region), describe, masks


def build_probes(cfg: dict) -> List[Probe]:
    probes: List[Probe] = []
    if cfg["cast"]["release_when"]:
        probes.append(_detector_probe("cast-release", cfg["cast"]["release_when"]))
    if cfg["bite"]["method"] == "detect" and cfg["bite"]["detector"]:
        probes.append(_detector_probe("bite", cfg["bite"]["detector"]))
    r = cfg["reel"]
    if r["active_detector"]:
        probes.append(_detector_probe("reel-active", r["active_detector"]))

    if r["method"] == "bar" and r["bar"]["region"]:
        b = r["bar"]
        axis = "x" if b["hold_moves"] in ("right", "left") else "y"

        def bar_desc(img: np.ndarray) -> str:
            fish = find_span(color_mask(img, b["fish_color"], b["tolerance"]), axis, b["max_gap"], b["min_pixels"])
            bar = find_span(color_mask(img, b["bar_color"], b["tolerance"]), axis, b["max_gap"], b["min_pixels"])
            f = f"{span_center(fish):.0f}" if fish else "not found"
            br = f"{bar[0]}-{bar[1]}" if bar else "not found"
            return f"bar: fish at {f}, your bar at {br}"

        def bar_masks(img: np.ndarray):
            return [(color_mask(img, b["bar_color"], b["tolerance"]), (0, 255, 255)),
                    (color_mask(img, b["fish_color"], b["tolerance"]), (255, 0, 255))]

        probes.append(("bar", list(b["region"]), bar_desc, bar_masks))

    if r["method"] == "zone" and r["zone"]["region"]:
        z = r["zone"]
        region = z["region"]
        axis = z["axis"] if z["axis"] != "auto" else ("x" if region[2] >= region[3] else "y")

        def zone_desc(img: np.ndarray) -> str:
            m = find_span(color_mask(img, z["marker_color"], z["tolerance"]), axis, z["max_gap"], z["min_pixels"])
            t = find_span(color_mask(img, z["target_color"], z["tolerance"]), axis, z["max_gap"], z["min_pixels"])
            ms = f"{span_center(m):.0f}" if m else "not found"
            ts = f"{t[0]}-{t[1]}" if t else "not found"
            return f"zone: marker at {ms}, target zone {ts}"

        def zone_masks(img: np.ndarray):
            return [(color_mask(img, z["target_color"], z["tolerance"]), (0, 255, 255)),
                    (color_mask(img, z["marker_color"], z["tolerance"]), (255, 0, 255))]

        probes.append(("zone", list(region), zone_desc, zone_masks))

    if r["method"] == "target" and r["target"]["region"]:
        t = r["target"]

        def target_desc(img: np.ndarray) -> str:
            mask = color_mask(img, t["color"], t["tolerance"])
            n = int(mask.sum())
            c = blob_center(mask, t["max_gap"]) if n >= t["min_pixels"] else None
            where = f"would click at {c[0]:.0f},{c[1]:.0f} inside the region" if c else "nothing to click"
            return f"target: {n}px (need {t['min_pixels']}) -> {where}"

        def target_masks(img: np.ndarray):
            return [(color_mask(img, t["color"], t["tolerance"]), (255, 0, 255))]

        probes.append(("target", list(t["region"]), target_desc, target_masks))
    return probes


def save_debug_images(screen, probes: List[Probe], out_dir: str) -> List[str]:
    os.makedirs(out_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    paths = []
    full, (ox, oy) = screen.grab_full()
    full = full.copy()
    for label, region, _desc, masks in probes:
        x, y, w, h = region
        draw_rect(full, x - ox - 2, y - oy - 2, w + 4, h + 4, (255, 0, 255), 2)
        crop = screen.grab(region).copy()
        for mask, color in masks(crop):
            crop[mask] = color
        scale = max(1, min(8, 400 // max(w, h)))  # blow small regions up so they're easy to see
        crop = np.repeat(np.repeat(crop, scale, axis=0), scale, axis=1)
        path = os.path.join(out_dir, f"{stamp}-{label}-matches.png")
        write_png(path, crop)
        paths.append(path)
    path = os.path.join(out_dir, f"{stamp}-screen.png")
    write_png(path, full)
    paths.insert(0, path)
    return paths


def run_check(cfg: dict, screen, out_dir: str) -> None:
    probes = build_probes(cfg)
    key = cfg["hotkeys"]["capture"]
    if not probes:
        print("Your config doesn't watch the screen at all (it only uses fixed timings),")
        print("so there is nothing to check. Run setup to add screen detection.")
        return
    shots: "queue.Queue[bool]" = queue.Queue()
    listener = HotkeyListener({key: lambda: shots.put(True)}).start()
    print("Showing what the macro sees, 4 times a second. Play normally and watch the values change.")
    print(f"Press {key.upper()} to save debug screenshots to '{out_dir}' (matching pixels are painted"
          " pink/cyan). Ctrl+C to exit.\n")
    try:
        while True:
            parts = []
            for _label, region, describe, _masks in probes:
                try:
                    parts.append(describe(screen.grab(region)))
                except Exception as e:
                    parts.append(f"{_label}: error {e}")
            print(" | ".join(parts))
            if not shots.empty():
                shots.get()
                for p in save_debug_images(screen, probes, out_dir):
                    print(f"  saved {p}")
            time.sleep(0.25)
    except KeyboardInterrupt:
        print()
    finally:
        listener.stop()
