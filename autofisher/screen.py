"""Reading pixels off the screen with mss (fast, works with Roblox in windowed or fullscreen)."""
from __future__ import annotations

import threading
from typing import Sequence, Tuple

import numpy as np


class MssScreen:
    def __init__(self) -> None:
        import mss  # noqa: F401  (fail early with a clear error if missing)

        self._local = threading.local()  # mss objects must not be shared between threads

    def _sct(self):
        sct = getattr(self._local, "sct", None)
        if sct is None:
            import mss

            sct = mss.mss()
            self._local.sct = sct
        return sct

    def grab(self, region: Sequence[int]) -> np.ndarray:
        """RGB image (h, w, 3) of [x, y, width, height] in screen coordinates."""
        x, y, w, h = (int(v) for v in region)
        shot = self._sct().grab({"left": x, "top": y, "width": w, "height": h})
        bgra = np.frombuffer(shot.bgra, dtype=np.uint8).reshape(shot.height, shot.width, 4)
        return np.ascontiguousarray(bgra[:, :, 2::-1])  # BGR(A) -> RGB

    def pixel(self, x: int, y: int) -> Tuple[int, int, int]:
        img = self.grab((x, y, 1, 1))
        r, g, b = img[0, 0]
        return int(r), int(g), int(b)

    def grab_full(self) -> Tuple[np.ndarray, Tuple[int, int]]:
        """Screenshot of every monitor. Returns (image, (left, top) of the image on screen)."""
        mon = self._sct().monitors[0]
        img = self.grab((mon["left"], mon["top"], mon["width"], mon["height"]))
        return img, (mon["left"], mon["top"])
