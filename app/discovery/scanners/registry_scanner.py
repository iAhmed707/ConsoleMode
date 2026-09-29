"""Registry uninstall scanner (64-bit + 32-bit views, HKLM + HKCU).

Windows publishes Win32 uninstall information under three physical locations
on a 64-bit machine:

* ``HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall``  (native view)
* ``HKLM\\SOFTWARE\\WOW6432Node\\...\\Uninstall`` (32-bit view; Windows maps
  this transparently to the *same* path when the registry is opened with the
  ``KEY_WOW64_32KEY`` flag, so we do not hard-code ``WOW6432Node``)
* ``HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall`` (per-user)

The Python equivalent of C# ``RegistryView.Registry64``/``Registry32`` is the
``access`` argument to ``winreg.OpenKey``: ``KEY_WOW64_64KEY`` (0x0100) forces
the 64-bit view and ``KEY_WOW64_32KEY`` (0x0200) forces the 32-bit view,
regardless of the bitness of the running Python interpreter.  For HKCU the two
views coincide, so the flags are omitted.
"""

from __future__ import annotations

import os
from typing import List

try:
    import winreg
except ImportError:  # pragma: no cover - non-Windows host
    winreg = None

from ..commandline import split_executable, strip_icon_index
from ..models import (
    ARCH_UNKNOWN,
    ARCH_X86,
    ARCH_X64,
    RawDiscoveryItem,
    SOURCE_REGISTRY,
)
from .base import BaseScanner, make_id

KEY_WOW64_64KEY = 0x0100
KEY_WOW64_32KEY = 0x0200
KEY_READ = 0x20019

# (label, hive, path, view flags).  View flags matter for HKLM only.
_UNINSTALL_ROOTS = [
    ("HKLM64", "HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", KEY_WOW64_64KEY),
    ("HKLM32", "HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", KEY_WOW64_32KEY),
    ("HKCU", "HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", 0),
]

# Values we read from each uninstall subkey (the documented Win32 set).
_VALUES = (
    "DisplayName", "DisplayVersion", "Publisher", "InstallLocation",
    "UninstallString", "QuietUninstallString", "DisplayIcon", "InstallDate",
    "EstimatedSize", "WindowsInstaller", "SystemComponent", "ReleaseType",
    "NoRemove", "NoModify", "NoRepair", "ParentKeyName", "ParentDisplayName",
    "Language", "Comments", "URLInfoAbout", "HelpLink", "Readme",
)

# Classification-relevant flags copied into the item's ``flags`` dict.
_FLAG_KEYS = (
    "WindowsInstaller", "SystemComponent", "ReleaseType", "NoRemove",
    "NoModify", "NoRepair", "ParentKeyName", "ParentDisplayName", "Language",
)


class RegistryScanner(BaseScanner):
    name = "Registry"

    def scan(self) -> List[RawDiscoveryItem]:
        if winreg is None:
            return []

        items: List[RawDiscoveryItem] = []
        for label, hive_name, path, view in _UNINSTALL_ROOTS:
            hive = (winreg.HKEY_LOCAL_MACHINE if hive_name == "HKLM"
                    else winreg.HKEY_CURRENT_USER)
            items.extend(self._scan_root(label, hive, path, view))
        return items

    def _scan_root(self, label, hive, path, view) -> List[RawDiscoveryItem]:
        items: List[RawDiscoveryItem] = []
        access = KEY_READ | view
        try:
            key = winreg.OpenKey(hive, path, 0, access)
        except OSError:
            return items

        try:
            count = winreg.QueryInfoKey(key)[0]
            for index in range(count):
                try:
                    subkey_name = winreg.EnumKey(key, index)
                except OSError:
                    continue
                item = self._item_from_subkey(label, hive, path, subkey_name, view)
                if item is not None:
                    items.append(item)
        finally:
            winreg.CloseKey(key)
        return items

    def _item_from_subkey(self, label, hive, path, subkey_name, view):
        full_path = "%s\\%s" % (path, subkey_name)
        try:
            subkey = winreg.OpenKey(hive, full_path, 0, KEY_READ | view)
        except OSError:
            return None

        try:
            values = self._read_values(subkey)
        finally:
            winreg.CloseKey(subkey)

        # Registry values mix REG_SZ (str) and REG_DWORD (int); normalise to
        # strings here so the rest of the pipeline never calls .strip() on an
        # integer (e.g. the "Language" LCID value).
        def s(value_name):
            value = values.get(value_name)
            return "" if value is None else str(value).strip()

        name = s("DisplayName")
        if not name:
            # Sub-components often carry a ParentKeyName instead of a
            # DisplayName; they are not standalone programs.
            return None

        is_msi = _as_bool(values.get("WindowsInstaller"))
        product_code = _normalise_guid(subkey_name) if _looks_like_guid(subkey_name) else ""

        display_icon = s("DisplayIcon")
        icon_exe = _icon_exe(display_icon)

        uninstall_string = s("UninstallString")
        uninstall_exe, uninstall_args = split_executable(uninstall_string)

        flags = {
            "WindowsInstaller": is_msi,
            "SystemComponent": _as_bool(values.get("SystemComponent")),
            "ReleaseType": s("ReleaseType"),
            "NoRemove": _as_bool(values.get("NoRemove")),
            "NoModify": _as_bool(values.get("NoModify")),
            "NoRepair": _as_bool(values.get("NoRepair")),
            "ParentKeyName": s("ParentKeyName"),
            "ParentDisplayName": s("ParentDisplayName"),
            "Language": s("Language"),
        }

        try:
            estimated_size = int(values.get("EstimatedSize") or 0)
        except (TypeError, ValueError):
            estimated_size = 0

        item = RawDiscoveryItem(
            id=make_id("registry", label, subkey_name),
            name=name,
            version=s("DisplayVersion"),
            publisher=s("Publisher"),
            install_location=s("InstallLocation"),
            uninstall_string=uninstall_string,
            quiet_uninstall_string=s("QuietUninstallString"),
            display_icon=display_icon,
            install_date=s("InstallDate"),
            estimated_size=estimated_size,
            source=SOURCE_REGISTRY,
            architecture=_view_architecture(label),
            installer_type="msi" if is_msi else "exe",
            product_code=product_code,
            executable_path=icon_exe,
            flags=flags,
        )
        item.extra.update({
            "registry_view": label,
            "registry_key": subkey_name,
            "uninstall_exe": uninstall_exe,
            "uninstall_args": uninstall_args,
            "comments": s("Comments"),
            "url_info_about": s("URLInfoAbout"),
        })
        return item

    @staticmethod
    def _read_values(subkey) -> dict:
        values = {}
        for name in _VALUES:
            try:
                value, _ = winreg.QueryValueEx(subkey, name)
            except OSError:
                continue
            values[name] = value
        return values


def _as_bool(value) -> bool:
    """REG_DWORD is 0/1; treat any non-zero / non-empty value as truthy."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    try:
        return int(value) != 0
    except (TypeError, ValueError):
        return bool(value)


def _view_architecture(label: str) -> str:
    """The registry *view* is only a hint about architecture; the normalizer
    overrides it with the PE header when a real executable is available."""
    if label == "HKLM32":
        return ARCH_X86
    if label == "HKLM64":
        return ARCH_X64
    return ARCH_UNKNOWN


def _looks_like_guid(text: str) -> bool:
    text = text.strip("{}")
    parts = text.split("-")
    return len(parts) == 5 and all(len(p) in (8, 4, 4, 4, 12) for p in parts)


def _normalise_guid(text: str) -> str:
    """Canonical GUID form: uppercase, braces stripped."""
    return text.strip("{}").strip().upper()


def _icon_exe(display_icon: str) -> str:
    """Best-effort executable path from a ``DisplayIcon`` value."""
    if not display_icon:
        return ""
    raw = strip_icon_index(display_icon)
    raw = os.path.expandvars(raw)
    if not raw.lower().endswith(".exe"):
        return ""
    try:
        return raw if os.path.isfile(raw) else ""
    except OSError:
        return ""
