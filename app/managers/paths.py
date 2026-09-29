"""Filesystem locations shared by the managers.

The application stores its own files (settings, logs) and user data (profiles)
next to the executable when frozen, or next to the source tree otherwise.
"""

import sys
from pathlib import Path


def app_dir():
    """The folder ConsoleMode runs from (beside the .exe, or the source root)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def default_profiles_dir():
    """``profiles/`` beside the application."""
    return app_dir() / "profiles"
