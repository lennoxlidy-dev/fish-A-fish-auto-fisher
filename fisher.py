#!/usr/bin/env python3
"""Fish A Fish auto fisher.

    python fisher.py setup    # first time: teach it how the game looks on your screen
    python fisher.py          # run it (F6 start/pause, F7 quit)
    python fisher.py check    # see live what the screen detection sees
    python fisher.py picker   # live mouse position + colour, for editing config.json by hand
"""
import sys

if sys.version_info < (3, 8):
    sys.exit("Python 3.8 or newer is required (get it from python.org).")

from autofisher.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
