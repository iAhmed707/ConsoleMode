"""Start Menu and Desktop shortcut scanner.

Shortcuts are a *secondary* source: they are the most reliable way to recover
the actual launch executable for a Win32 program, but they are never the
primary identity of a program.  AppX shortcuts have no ``TargetPath`` (they
target a package), so they are skipped here — the AppX scanner covers them.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

from ..models import Component, RawDiscoveryItem, SOURCE_SHORTCUT
from ._shell import com_shell, resolve_shortcut
from .base import BaseScanner, make_id


class ShortcutScanner(BaseScanner):
    name = "Shortcut"

    def scan(self) -> List[RawDiscoveryItem]:
        items: List[RawDiscoveryItem] = []
        with com_shell() as shell:
            for folder in _shortcut_folders():
                for lnk in _iter_lnks(folder):
                    target, args, _ = resolve_shortcut(shell, str(lnk))
                    if not target or not target.lower().endswith(".exe"):
                        continue
                    if not os.path.isfile(target):
                        continue
                    item = RawDiscoveryItem(
                        id=make_id("shortcut", str(lnk)),
                        name=lnk.stem,
                        executable_path=target,
                        source=SOURCE_SHORTCUT,
                        components=[Component(
                            kind="shortcut", name=lnk.stem, path=target,
                            details={"folder": str(lnk.parent), "arguments": args},
                        )],
                    )
                    item.extra.update({"folder": str(lnk.parent), "arguments": args})
                    items.append(item)
        return items


def _shortcut_folders() -> List[Path]:
    folders = []
    # Start Menu (per-user and common).
    for env_var in ("APPDATA", "ProgramData"):
        base = os.environ.get(env_var)
        if base:
            folders.append(Path(base) / "Microsoft/Windows/Start Menu/Programs")
    # Desktop (per-user and public).
    for env_var in ("USERPROFILE", "PUBLIC"):
        base = os.environ.get(env_var)
        if base:
            folders.append(Path(base) / "Desktop")
    return folders


def _iter_lnks(folder: Path) -> List[Path]:
    try:
        return [p for p in folder.rglob("*.lnk")]
    except OSError:
        return []
