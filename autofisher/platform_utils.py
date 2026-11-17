"""Small Windows-specific fixes. Everything here is a harmless no-op on other systems."""
from __future__ import annotations

import ctypes
import sys
from typing import Optional


def enable_dpi_awareness() -> None:
    """Make screen pixels and mouse coordinates agree when Windows display scaling isn't 100%."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor DPI aware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def enable_high_res_timer() -> None:
    """Ask Windows for 1 ms sleep accuracy (default is ~15 ms), needed for fast clicking."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass


def foreground_window_title() -> Optional[str]:
    if sys.platform != "win32":
        return None
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value
    except Exception:
        return None


def roblox_focused() -> Optional[bool]:
    """True/False on Windows, None when we can't tell (other systems)."""
    title = foreground_window_title()
    if title is None:
        return None
    return title.strip().lower() == "roblox"
