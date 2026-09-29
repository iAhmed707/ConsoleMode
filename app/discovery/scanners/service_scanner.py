"""Windows service scanner (WMI ``Win32_Service``).

Services are a *component* source: they usually belong to an installed program
rather than standing alone.  We enumerate them read-only through the official
WMI ``Win32_Service`` class (via the ``Get-CimInstance`` cmdlet, which is the
same WMI/Win32 provider the Win32 ``QueryServiceConfig`` API exposes).  Each
service carries its binary path so the deduplication engine can attach it to
the owning application.

Kernel drivers (``.sys``) and ``svchost``-hosted services are flagged so the
classification layer does not show them as launchable programs.
"""

from __future__ import annotations

import os
from typing import List

from ..commandline import split_executable
from ..models import Component, RawDiscoveryItem, SOURCE_SERVICE
from ..powershell import run_json
from .base import BaseScanner, make_id

_QUERY = r"""
$ErrorActionPreference = 'SilentlyContinue'
Get-CimInstance Win32_Service | ForEach-Object {
    [pscustomobject]@{
        Name = [string]$_.Name
        DisplayName = [string]$_.DisplayName
        State = [string]$_.State
        StartMode = [string]$_.StartMode
        PathName = [string]$_.PathName
        Description = [string]$_.Description
    }
} | ConvertTo-Json -Depth 3 -Compress
"""


class ServiceScanner(BaseScanner):
    name = "Service"

    def scan(self) -> List[RawDiscoveryItem]:
        result = run_json(_QUERY, timeout=30.0)
        if result is None:
            return []
        if isinstance(result, dict):
            result = [result]

        items: List[RawDiscoveryItem] = []
        for service in result:
            if not isinstance(service, dict):
                continue
            item = self._item(service)
            if item is not None:
                items.append(item)
        return items

    def _item(self, service) -> RawDiscoveryItem:
        name = (service.get("Name") or "").strip()
        display_name = (service.get("DisplayName") or "").strip()
        path_name = (service.get("PathName") or "").strip()
        if not name and not display_name:
            return None

        exe, args = split_executable(path_name)
        exe = _clean_service_path(exe)

        is_driver = exe.lower().endswith(".sys")
        hosted = "svchost.exe" in exe.lower()
        launch_path = exe if (exe and os.path.isfile(exe) and not is_driver and not hosted) else ""

        details = {
            "state": (service.get("State") or "").strip(),
            "start_mode": (service.get("StartMode") or "").strip(),
            "description": (service.get("Description") or "").strip(),
            "binary_path": path_name,
            "arguments": args,
            "is_driver": is_driver,
            "hosted": hosted,
        }

        item = RawDiscoveryItem(
            id=make_id("service", name or display_name),
            name=display_name or name,
            publisher="",
            install_location=os.path.dirname(exe) if exe else "",
            executable_path=launch_path,
            source=SOURCE_SERVICE,
            installer_type="service",
            components=[Component(kind="service", name=name or display_name,
                                  path=exe, details=dict(details))],
        )
        item.extra.update(details)
        return item


def _clean_service_path(exe: str) -> str:
    """Strip Win32 device-path prefixes like ``\\??\\C:\\...``."""
    exe = (exe or "").strip()
    if exe.startswith("\\??\\"):
        exe = exe[4:]
    return exe
