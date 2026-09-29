"""Optional "Portable Software Discovery" scanner.

Portable apps never appear in the uninstall registry, so they can only be
found by scanning folders the user points at.  This scanner is **off by
default** and, when enabled, walks a bounded set of folders:

* Every ``.exe`` is *not* treated as a program.
* System binaries (under the Windows directory) are ignored.
* Obvious installer/updater/uninstaller names are ignored.
* PE metadata (``CompanyName`` / ``ProductName`` / ``FileVersion``) is read so
  related files can be grouped into one logical application.

Grouping by ``(CompanyName, ProductName)`` drastically cuts false positives,
but portable discovery is still inherently heuristic — see DISCOVERY.md.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

from .. import pe
from ..models import Component, RawDiscoveryItem, SOURCE_PORTABLE
from .base import BaseScanner, make_id

# Names that almost always belong to an installer, not a portable app.
_SKIP_NAME_TOKENS = (
    "setup", "install", "uninstall", "unins", "update", "updater", "vcredist",
    "redist", "redistributable", "crashpad", "unins000", "repair", "stub",
    "package", "packagemanager", "installer", "patch",
)

_SYSTEM_ROOTS = (r"C:\Windows", r"C:\Windows\System32", r"C:\Windows\SysWOW64")


class PortableScanner(BaseScanner):
    name = "Portable"

    def __init__(self, folders: Optional[List[str]] = None, max_depth: int = 3,
                 max_files: int = 2000):
        self.folders = folders or _default_folders()
        self.max_depth = max_depth
        self.max_files = max_files

    def scan(self) -> List[RawDiscoveryItem]:
        candidates: List[str] = []
        for folder in self.folders:
            if len(candidates) >= self.max_files:
                break
            candidates.extend(self._walk(Path(folder)))

        groups: Dict[str, dict] = {}
        for exe in candidates:
            info = pe.get_pe_info(exe)
            key = self._group_key(exe, info)
            bucket = groups.setdefault(key, {
                "name": info.get("ProductName") or Path(exe).stem,
                "version": info.get("FileVersion") or "",
                "publisher": info.get("CompanyName") or "",
                "exes": [],
            })
            bucket["exes"].append((exe, info))

        items: List[RawDiscoveryItem] = []
        for key, bucket in groups.items():
            representative = self._representative(bucket["exes"])
            if not representative:
                continue
            path, info = representative
            item = RawDiscoveryItem(
                id=make_id("portable", key),
                name=bucket["name"] or Path(path).stem,
                version=bucket["version"] or info.get("FileVersion") or "",
                publisher=bucket["publisher"] or info.get("CompanyName") or "",
                install_location=str(Path(path).parent),
                executable_path=path,
                source=SOURCE_PORTABLE,
                architecture=info.get("architecture") or "unknown",
                installer_type="portable",
                components=[Component(kind="executable", path=path,
                                      name=bucket["name"] or Path(path).stem)],
            )
            item.extra["related_executables"] = [p for p, _ in bucket["exes"]]
            items.append(item)
        return items

    # ------------------------------------------------------------------ #
    def _walk(self, folder: Path) -> List[str]:
        found: List[str] = []
        if not folder.is_dir():
            return found
        try:
            for current, dirs, files in os.walk(folder):
                depth = len(Path(current).relative_to(folder).parts)
                if depth > self.max_depth:
                    dirs[:] = []
                    continue
                dirs[:] = [d for d in dirs if not self._is_system_dir(Path(current) / d)]
                for name in files:
                    if len(found) >= self.max_files:
                        return found
                    if name.lower().endswith(".exe") and not self._skip_name(name):
                        found.append(str(Path(current) / name))
        except OSError:
            pass
        return found

    @staticmethod
    def _is_system_dir(path: Path) -> bool:
        text = str(path).lower()
        return text in _SYSTEM_ROOTS or text.startswith(r"c:\windows")

    @staticmethod
    def _skip_name(name: str) -> bool:
        base = name.lower()
        if base.endswith(".exe"):
            base = base[:-4]
        return any(token in base for token in _SKIP_NAME_TOKENS)

    @staticmethod
    def _group_key(exe: str, info: Dict[str, str]) -> str:
        company = (info.get("CompanyName") or "").strip().lower()
        product = (info.get("ProductName") or "").strip().lower()
        if product:
            return "%s|%s" % (company, product)
        return "file|%s" % Path(exe).stem.lower()

    @staticmethod
    def _representative(exes):
        if not exes:
            return None
        # Prefer the largest executable (most likely the main one) among a
        # group that shares ProductName/CompanyName.
        return sorted(exes, key=lambda pair: -(pair[1].get("size") or 0))[0]


def _default_folders() -> List[str]:
    folders = []
    for env_var in ("USERPROFILE",):
        base = os.environ.get(env_var)
        if not base:
            continue
        for sub in ("Desktop", "Downloads", "Documents"):
            candidate = Path(base) / sub
            if candidate.is_dir():
                folders.append(str(candidate))
    return folders
