"""
Runtime path resolution for both development and PyInstaller frozen builds.

When frozen by PyInstaller, sys._MEIPASS points to the temp extraction
directory containing all bundled files. In dev, we use the repo root.
"""

import sys
import pathlib


def get_root() -> pathlib.Path:
    """Return the project root in both frozen and dev modes."""
    if getattr(sys, "frozen", False):
        return pathlib.Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return pathlib.Path(__file__).resolve().parent.parent


ROOT = get_root()
