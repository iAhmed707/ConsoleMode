"""Shared helper for resolving ``.lnk`` shortcuts through WScript.Shell COM.

COM must be initialised on the thread that uses it, so the shell object is
created inside a context manager that brackets the work with
``CoInitialize``/``CoUninitialize``.  Nothing here mutates the shortcut.
"""

from __future__ import annotations

import contextlib
from typing import Optional, Tuple


@contextlib.contextmanager
def com_shell():
    """Yield a ``WScript.Shell`` for the current thread, or ``None`` on failure."""
    shell = None
    try:
        import comtypes
        import comtypes.client
        comtypes.CoInitialize()
    except Exception:
        try:
            yield None
        finally:
            return

    try:
        try:
            shell = comtypes.client.CreateObject("WScript.Shell")
        except Exception:
            shell = None
        yield shell
    finally:
        try:
            comtypes.CoUninitialize()
        except Exception:
            pass


def resolve_shortcut(shell, lnk_path: str) -> Tuple[str, str, str]:
    """Return ``(target, arguments, working_directory)`` for a ``.lnk``."""
    if shell is None:
        return "", "", ""
    try:
        raw = shell.CreateShortcut(str(lnk_path))
        # CreateShortcut returns a bare IDispatch pointer; wrap it so comtypes
        # dynamic dispatch exposes TargetPath / Arguments / WorkingDirectory.
        from comtypes.client import dynamic
        sc = dynamic.Dispatch(raw)
        return (sc.TargetPath or "", sc.Arguments or "", sc.WorkingDirectory or "")
    except Exception:
        return "", "", ""
