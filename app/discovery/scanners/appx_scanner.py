"""AppX / MSIX (Microsoft Store) package scanner.

The canonical API is the WinRT ``Windows.Management.Deployment.PackageManager``
surface.  Driving WinRT directly from ``ctypes`` is impractical, so we use the
documented PowerShell cmdlet ``Get-AppxPackage`` (which itself wraps
``PackageManager``) as a fallback, plus ``Get-StartApps`` to recover the
``AppUserModelId`` used to *launch* a Store app.  One PowerShell process is
spawned for the whole query; never one per package.

Framework, resource and system packages are *reported* (so dedup can attach
them) but are not surfaced as ordinary programs by the classification layer.
"""

from __future__ import annotations

import json
from typing import Dict, List

from ..models import RawDiscoveryItem, SOURCE_APPX
from ..powershell import run_json
from .base import BaseScanner, make_id

_QUERY = r"""
$ErrorActionPreference = 'SilentlyContinue'
$packages = @(Get-AppxPackage | ForEach-Object {
    $pi = @($_.PackageUserInformation)
    [pscustomobject]@{
        Name = [string]$_.Name
        Publisher = [string]$_.Publisher
        Version = [string]$_.Version
        Architecture = [string]$_.Architecture
        PackageFullName = [string]$_.PackageFullName
        PackageFamilyName = [string]$_.PackageFamilyName
        InstallLocation = [string]$_.InstallLocation
        IsFramework = [bool]$_.IsFramework
        IsResourcePackage = [bool]$_.IsResourcePackage
        IsBundle = [bool]$_.IsBundle
        SignatureKind = [string]$_.SignatureKind
        InstallState = ($pi | ForEach-Object { [string]$_.InstallState }) -join ';'
    }
})
$startApps = @(Get-StartApps | ForEach-Object {
    [pscustomobject]@{ Name = [string]$_.Name; AppID = [string]$_.AppID }
})
[pscustomobject]@{ Packages = $packages; StartApps = $startApps } | ConvertTo-Json -Depth 5 -Compress
"""

_ARCH_MAP = {
    "X86": "x86",
    "X64": "x64",
    "AMD64": "x64",
    "ARM64": "arm64",
    "ARM": "arm",
    "NEUTRAL": "neutral",
}


class AppxScanner(BaseScanner):
    name = "AppX"

    def scan(self) -> List[RawDiscoveryItem]:
        result = run_json(_QUERY, timeout=45.0)
        if not result:
            return []

        packages = _as_list(result.get("Packages")) if isinstance(result, dict) else []
        start_apps = _as_list(result.get("StartApps")) if isinstance(result, dict) else []
        family_map, name_map = self._build_aumid_index(start_apps)

        items: List[RawDiscoveryItem] = []
        for package in packages:
            item = self._item(package, family_map, name_map)
            if item is not None:
                items.append(item)
        return items

    @staticmethod
    def _build_aumid_index(start_apps):
        """Index AUMIDs by package family name and by friendly name.

        An AUMID is ``<PackageFamilyName>!<AppId>`` and ``Get-StartApps``
        returns that exact string as ``AppID``, so the family name is the
        reliable link back to a package (the friendly Start-menu name may
        differ from the package name).
        """
        by_family: Dict[str, tuple] = {}
        by_name: Dict[str, str] = {}
        for app in start_apps:
            if not isinstance(app, dict):
                continue
            app_id = (app.get("AppID") or "").strip()
            name = (app.get("Name") or "").strip()
            if not app_id:
                continue
            if name:
                by_name.setdefault(name.lower(), app_id)
            if "!" in app_id:
                family = app_id.split("!", 1)[0]
                by_family.setdefault(family, (name, app_id))
        return by_family, by_name

    def _item(self, package, family_map, name_map) -> RawDiscoveryItem:
        if not isinstance(package, dict):
            return None

        family = (package.get("PackageFamilyName") or "").strip()
        short_name = (package.get("Name") or "").strip()
        package_full = (package.get("PackageFullName") or "").strip()

        # Prefer the friendly Start-menu name; fall back to the package name.
        display_name = short_name
        app_user_model_id = name_map.get(short_name.lower(), "")
        family_entry = family_map.get(family)
        if family_entry:
            friendly_name, aumid = family_entry
            if friendly_name:
                display_name = friendly_name
            app_user_model_id = aumid

        is_framework = bool(package.get("IsFramework"))
        is_resource = bool(package.get("IsResourcePackage"))
        package_type = "framework" if is_framework else ("resource" if is_resource else "app")

        item = RawDiscoveryItem(
            id=make_id("appx", package_full or family or short_name),
            name=display_name,
            version=(package.get("Version") or "").strip(),
            publisher=(package.get("Publisher") or "").strip(),
            install_location=(package.get("InstallLocation") or "").strip(),
            source=SOURCE_APPX,
            architecture=_ARCH_MAP.get((package.get("Architecture") or "").strip().upper(),
                                       "neutral"),
            installer_type="appx",
            package_full_name=package_full,
            package_family_name=family,
            app_user_model_id=app_user_model_id,
            is_framework=is_framework,
            is_resource=is_resource,
            package_type=package_type,
        )
        item.extra.update({
            "signature_kind": (package.get("SignatureKind") or "").strip(),
            "install_state": (package.get("InstallState") or "").strip(),
            "is_bundle": bool(package.get("IsBundle")),
            "display_name": display_name,
        })
        if item.app_user_model_id:
            item.launch_path = "shell:AppsFolder\\%s" % item.app_user_model_id
        return item


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]
