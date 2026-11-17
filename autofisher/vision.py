"""Pure image helpers (numpy only, no screen access) so they can be unit tested.

Images are numpy arrays shaped (height, width, 3) in RGB order.
Regions are [x, y, width, height] in screen pixels.
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

import numpy as np

Span = Tuple[int, int, int]  # (start, end, pixel_mass) along one axis, end inclusive


def normalize_colors(color) -> np.ndarray:
    """Accept [r, g, b] or [[r, g, b], ...] and return an int16 array shaped (k, 3)."""
    arr = np.asarray(color, dtype=np.int16)
    if arr.ndim == 1:
        arr = arr[None, :]
    if arr.ndim != 2 or arr.shape[1] != 3 or arr.shape[0] == 0:
        raise ValueError(f"expected an [R, G, B] color or a list of them, got {color!r}")
    return arr


def color_mask(img: np.ndarray, color, tolerance: int) -> np.ndarray:
    """Boolean mask of pixels within `tolerance` (per channel) of any of the given colors."""
    colors = normalize_colors(color)
    px = img[..., :3].astype(np.int16)
    mask = np.zeros(px.shape[:2], dtype=bool)
    for c in colors:
        mask |= np.abs(px - c).max(axis=-1) <= tolerance
    return mask


def find_span(mask: np.ndarray, axis: str, max_gap: int = 3, min_pixels: int = 1) -> Optional[Span]:
    """Find the biggest group of matching pixels along one axis.

    The mask is squashed onto the axis ("x" = columns, "y" = rows). Neighbouring
    columns/rows with matches are grouped together, allowing holes of up to
    `max_gap` empty columns/rows (e.g. where the fish icon covers the bar).
    Returns (start, end, mass) of the group with the most matching pixels, or
    None if nothing (or fewer than `min_pixels`) matched.
    """
    if axis not in ("x", "y"):
        raise ValueError("axis must be 'x' or 'y'")
    profile = mask.sum(axis=0 if axis == "x" else 1)
    idx = np.flatnonzero(profile)
    if idx.size == 0:
        return None
    breaks = np.flatnonzero(np.diff(idx) > max_gap + 1)
    starts = np.concatenate(([0], breaks + 1))
    ends = np.concatenate((breaks, [idx.size - 1]))
    best: Optional[Span] = None
    for s, e in zip(starts, ends):
        a, b = int(idx[s]), int(idx[e])
        mass = int(profile[a:b + 1].sum())
        if best is None or mass > best[2]:
            best = (a, b, mass)
    if best is None or best[2] < min_pixels:
        return None
    return best


def span_center(span: Span) -> float:
    return (span[0] + span[1]) / 2.0


def blob_center(mask: np.ndarray, max_gap: int = 3, min_pixels: int = 1) -> Optional[Tuple[float, float]]:
    """Centre (x, y) of the biggest blob of matching pixels, inside the mask's coordinates."""
    xs = find_span(mask, "x", max_gap, min_pixels)
    if xs is None:
        return None
    sub = mask[:, xs[0]:xs[1] + 1]
    ys = find_span(sub, "y", max_gap, 1)
    if ys is None:
        return None
    # Re-centre x using only the rows of the chosen blob so two blobs side by side don't mix.
    xs2 = find_span(mask[ys[0]:ys[1] + 1, :], "x", max_gap, 1)
    cx = span_center(xs2) if xs2 is not None else span_center(xs)
    return cx, span_center(ys)


@dataclass
class Detector:
    """"Is <color> visible inside <region>?" -- the building block for bite / reel detection."""

    region: Tuple[int, int, int, int]
    colors: np.ndarray
    tolerance: int = 30
    min_pixels: int = 10
    invert: bool = False

    @classmethod
    def from_config(cls, d: dict) -> "Detector":
        return cls(
            region=tuple(int(v) for v in d["region"]),  # type: ignore[arg-type]
            colors=normalize_colors(d["color"]),
            tolerance=int(d.get("tolerance", 30)),
            min_pixels=int(d.get("min_pixels", 10)),
            invert=bool(d.get("invert", False)),
        )

    def count(self, img: np.ndarray) -> int:
        return int(color_mask(img, self.colors, self.tolerance).sum())

    def present(self, img: np.ndarray) -> bool:
        seen = self.count(img) >= self.min_pixels
        return seen != self.invert


# ---------------------------------------------------------------- debug images

def draw_rect(img: np.ndarray, x: int, y: int, w: int, h: int, color: Sequence[int], thickness: int = 2) -> None:
    """Draw a rectangle outline in place (clipped to the image)."""
    H, W = img.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    if x0 >= x1 or y0 >= y1:
        return
    c = np.asarray(color, dtype=img.dtype)
    t = thickness
    img[y0:min(y1, y0 + t), x0:x1] = c
    img[max(y0, y1 - t):y1, x0:x1] = c
    img[y0:y1, x0:min(x1, x0 + t)] = c
    img[y0:y1, max(x0, x1 - t):x1] = c


def write_png(path: str, img: np.ndarray) -> None:
    """Save an RGB uint8 image as PNG without needing Pillow."""
    img = np.ascontiguousarray(img[..., :3], dtype=np.uint8)
    h, w = img.shape[:2]
    raw = b"".join(b"\x00" + img[row].tobytes() for row in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 6))
           + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)
