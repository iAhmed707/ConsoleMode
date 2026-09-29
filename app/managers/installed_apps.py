"""Installed-applications manager (thin adapter over the discovery engine).

The heavy lifting lives in :mod:`app.discovery`: a Revo Uninstaller-style
pipeline that scans the uninstall registry (64/32-bit + HKCU), MSI, AppX/MSIX,
services, startup entries, scheduled tasks and shortcuts, then normalises,
deduplicates and classifies the results.

This adapter keeps the UI API simple: ``get_apps()`` returns a list of rich
dicts, each with the classic ``name`` / ``path`` / ``publisher`` keys plus the
extra fields the picker dialog shows (version, location, installer type,
architecture, confidence, classification, sources, components).
"""

from __future__ import annotations

import sys
from typing import Callable, List, Optional

from app.discovery import DiscoveryManager
from app.discovery.models import Application

IS_WINDOWS = sys.platform == "win32"


class InstalledAppsManager:
    """Lists installed programs as rich dicts via the discovery engine."""

    def __init__(self):
        self._apps: List[dict] = []
        self._engine = DiscoveryManager()

    # ------------------------------------------------------------------ #
    def is_available(self) -> bool:
        return IS_WINDOWS

    def unavailable_reason(self) -> Optional[str]:
        if self.is_available():
            return None
        return "Installed-applications listing is only supported on Windows."

    # ------------------------------------------------------------------ #
    def get_apps(self) -> List[dict]:
        """The cached app list, enumerating on first use."""
        if not self._apps:
            self.refresh()
        return self._apps

    def refresh(self, on_log: Optional[Callable[[str], None]] = None,
                cancel_event=None) -> List[dict]:
        """Run a full discovery and cache the rich app dicts."""
        if not self.is_available():
            self._apps = []
            return self._apps

        result = self._engine.discover(on_log=on_log, cancel_event=cancel_event)
        self._apps = [self._to_dict(app) for app in result.apps]
        return self._apps

    # ------------------------------------------------------------------ #
    @staticmethod
    def _to_dict(app: Application) -> dict:
        return {
            "name": app.name,
            "path": app.launch_path,
            "publisher": app.publisher,
            "version": app.version,
            "location": app.install_location,
            "installer_type": app.installer_type,
            "architecture": app.architecture,
            "confidence": app.confidence,
            "classification": app.classification,
            "sources": list(app.sources),
            "components": [c.to_dict() for c in app.components],
            "uninstall_command": app.uninstall_command,
            "quiet_uninstall_command": app.quiet_uninstall_command,
            "surfaceable": app.surfaceable,
            "launchable": app.launchable,
            "signature": dict(app.signature),
            "product_code": app.product_code,
            "app_user_model_id": app.app_user_model_id,
        }
