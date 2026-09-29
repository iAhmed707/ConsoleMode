"""Startup entry scanner (Run/RunOnce keys + Startup folders).

Startup entries are component metadata, not standalone programs.  We read the
classic auto-start locations read-only:

* ``HKLM\\...\\Run`` and ``RunOnce`` (both 64- and 32-bit views)
* ``HKCU\\...\\Run`` and ``RunOnce``
* the common and per-user Startup folders

Task Scheduler is handled separately by :class:`ScheduledTaskScanner`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

try:
    import winreg
except ImportError:  # pragma: no cover
    winreg = None

from ..commandline import split_executable
from ..models import Component, RawDiscoveryItem, SOURCE_STARTUP
from ._shell import com_shell, resolve_shortcut
from .base import BaseScanner, make_id

KEY_WOW64_64KEY = 0x0100
KEY_WOW64_32KEY = 0x0200
KEY_READ = 0x20019

_RUN_ROOTS = [
    ("HKLM64", "HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", KEY_WOW64_64KEY),
    ("HKLM32", "HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", KEY_WOW64_32KEY),
    ("HKCU", "HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", 0),
    ("HKLM64", "HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce", KEY_WOW64_64KEY),
    ("HKLM32", "HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce", KEY_WOW64_32KEY),
    ("HKCU", "HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce", 0),
]


class StartupScanner(BaseScanner):
    name = "Startup"

    def scan(self) -> List[RawDiscoveryItem]:
        items: List[RawDiscoveryItem] = []
        items.extend(self._scan_run_keys())
        items.extend(self._scan_startup_folders())
        return items

    def _scan_run_keys(self) -> List[RawDiscoveryItem]:
        if winreg is None:
            return []

        items: List[RawDiscoveryItem] = []
        for label, hive_name, path, view in _RUN_ROOTS:
            hive = (winreg.HKEY_LOCAL_MACHINE if hive_name == "HKLM"
                    else winreg.HKEY_CURRENT_USER)
            try:
                key = winreg.OpenKey(hive, path, 0, KEY_READ | view)
            except OSError:
                continue
            try:
                count = winreg.QueryInfoKey(key)[1]
                for index in range(count):
                    try:
                        value_name, value, _ = winreg.EnumValue(key, index)
                    except OSError:
                        continue
                    exe, args = split_executable(str(value or ""))
                    if not exe:
                        continue
                    item = RawDiscoveryItem(
                        id=make_id("startup", label, value_name),
                        name=(value_name or "").strip() or os.path.basename(exe),
                        executable_path=exe if os.path.isfile(exe) else "",
                        source=SOURCE_STARTUP,
                        components=[Component(
                            kind="startup",
                            name=(value_name or "").strip(),
                            path=exe,
                            details={"mechanism": "Registry Run/RunOnce",
                                     "hive": label, "command": str(value or ""),
                                     "arguments": args},
                        )],
                    )
                    item.extra.update({"mechanism": "Registry Run/RunOnce",
                                       "hive": label, "command": str(value or "")})
                    items.append(item)
            finally:
                winreg.CloseKey(key)
        return items

    def _scan_startup_folders(self) -> List[RawDiscoveryItem]:
        items: List[RawDiscoveryItem] = []
        with com_shell() as shell:
            for folder in _startup_folders():
                for entry in _iter_files(folder):
                    target, args, _ = resolve_shortcut(shell, str(entry)) if entry.suffix.lower() == ".lnk" else (str(entry), "", "")
                    if entry.suffix.lower() == ".exe":
                        target = str(entry)
                    if not target or not target.lower().endswith(".exe"):
                        continue
                    if not os.path.isfile(target):
                        continue
                    item = RawDiscoveryItem(
                        id=make_id("startup-folder", str(entry)),
                        name=entry.stem,
                        executable_path=target,
                        source=SOURCE_STARTUP,
                        components=[Component(
                            kind="startup", name=entry.stem, path=target,
                            details={"mechanism": "Startup folder",
                                     "folder": str(entry.parent), "arguments": args},
                        )],
                    )
                    item.extra.update({"mechanism": "Startup folder",
                                       "folder": str(entry.parent)})
                    items.append(item)
        return items


def _startup_folders() -> List[Path]:
    folders = []
    for env_var in ("ProgramData", "APPDATA"):
        base = os.environ.get(env_var)
        if base:
            folders.append(Path(base) / "Microsoft/Windows/Start Menu/Programs/StartUp")
    return folders


def _iter_files(folder: Path):
    try:
        return [p for p in folder.iterdir() if p.is_file()]
    except OSError:
        return []
