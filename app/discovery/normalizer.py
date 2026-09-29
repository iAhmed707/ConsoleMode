"""Normalisation layer: turns raw scanner output into clean, comparable items.

Responsibilities:

* trim whitespace and normalise versions,
* infer a missing ``install_location`` from the executable / uninstaller path,
* pick the best ``executable_path`` (never the uninstaller),
* resolve architecture from the PE header when a real executable exists,
* cache matching keys (``normalized_name`` / ``normalized_publisher``).

The normalizer never invents an install location that does not exist.
"""

from __future__ import annotations

import os
from typing import List

from . import pe
from .models import (
    ARCH_UNKNOWN,
    RawDiscoveryItem,
)
from .textutils import (
    normalize_guid,
    normalize_name,
    normalize_path,
    normalize_version,
)

_SYSTEM_DIRS = (r"c:\windows", r"c:\program files\windowsapps")


class Normalizer:
    def normalize_all(self, items: List[RawDiscoveryItem]) -> List[RawDiscoveryItem]:
        return [self.normalize(item) for item in items]

    def normalize(self, item: RawDiscoveryItem) -> RawDiscoveryItem:
        item.name = (item.name or "").strip()
        item.version = normalize_version(item.version)
        item.publisher = (item.publisher or "").strip()

        item.install_location = self._resolve_install_location(item)
        item.executable_path = self._resolve_executable(item)
        item.architecture = self._resolve_architecture(item)

        if not item.installer_type:
            item.installer_type = self._infer_installer(item)

        normalized_name = normalize_name(item.name)
        item.extra["normalized_name"] = normalized_name
        item.extra["normalized_publisher"] = normalize_name(item.publisher)
        item.extra["normalized_location"] = normalize_path(item.install_location)
        item.extra["normalized_executable"] = normalize_path(item.executable_path)
        item.extra["normalized_uninstall_exe"] = normalize_path(
            item.extra.get("uninstall_exe", "")
        )
        item.extra["normalized_product_code"] = normalize_guid(item.product_code)
        # Token set used as a cheap pre-filter before the (slower) fuzzy name
        # comparison in the deduplication engine.  Internal-only.
        item.extra["name_tokens"] = frozenset(normalized_name.split())
        return item

    # ------------------------------------------------------------------ #
    def _resolve_install_location(self, item: RawDiscoveryItem) -> str:
        location = (item.install_location or "").strip().strip('"')
        location = os.path.expandvars(location) if location else ""

        if not location:
            # Infer from the main executable (never from the uninstaller).
            exe = item.executable_path or ""
            if exe and os.path.isfile(exe) and not _in_system_dirs(exe):
                location = os.path.dirname(exe)
        return location

    def _resolve_executable(self, item: RawDiscoveryItem) -> str:
        exe = (item.executable_path or "").strip().strip('"')
        if exe:
            exe = os.path.expandvars(exe)
            if exe.lower().endswith(".exe") and os.path.isfile(exe):
                return exe
        return ""

    def _resolve_architecture(self, item: RawDiscoveryItem) -> str:
        # The PE header is authoritative when we have a real executable.
        exe = item.executable_path
        if exe and os.path.isfile(exe):
            arch = pe.read_architecture(exe)
            if arch != ARCH_UNKNOWN:
                return arch
        if item.architecture != ARCH_UNKNOWN:
            return item.architecture
        location = (item.install_location or "").lower()
        if "program files (x86)" in location:
            return "x86"
        return ARCH_UNKNOWN

    @staticmethod
    def _infer_installer(item: RawDiscoveryItem) -> str:
        source = (item.source or "").lower()
        if source == "msi":
            return "msi"
        if source in ("appx", "msix"):
            return "appx"
        if source == "portable":
            return "portable"
        if source == "service":
            return "service"
        if "msiexec" in (item.uninstall_string or "").lower():
            return "msi"
        return "exe"


def _in_system_dirs(path: str) -> bool:
    lowered = normalize_path(path)
    return any(lowered.startswith(d) for d in _SYSTEM_DIRS)
