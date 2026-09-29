"""Windows Installer (MSI) product scanner via the MSI API (``msi.dll``).

This calls the official Windows Installer functions directly through
``ctypes``:

* ``MsiEnumProductsW`` — enumerate installed/advertised MSI products for the
  current user (per-user *and* per-machine products the user can see),
* ``MsiGetProductInfoW`` — read a product property (ProductName, VersionString,
  Publisher, InstallLocation, LocalPackage, InstallDate, PackageCode,
  AssignmentType).

It links to the registry uninstall entries because those keys are named by the
MSI ProductCode GUID.

Why not WMI ``Win32_Product``?  Enumerating ``Win32_Product`` triggers a
documented *consistency check / reconfiguration* of every MSI product on the
machine, which can repair or reconfigure installs and is slow.  It is therefore
only acceptable as a last-resort, explicitly-requested source — never the
primary MSI discovery path.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import List

from ..models import RawDiscoveryItem, SOURCE_MSI
from .base import BaseScanner, make_id

_ERROR_NO_MORE_ITEMS = 259

# Property names accepted by MsiGetProductInfoW.
_PROPERTIES = (
    "ProductName",
    "VersionString",
    "Publisher",
    "InstallLocation",
    "LocalPackage",
    "InstallDate",
    "PackageCode",
    "AssignmentType",
)


class MsiScanner(BaseScanner):
    name = "MSI"

    def scan(self) -> List[RawDiscoveryItem]:
        try:
            msi = ctypes.WinDLL("msi.dll", use_last_error=True)
            msi.MsiEnumProductsW.argtypes = [wintypes.DWORD, wintypes.LPWSTR]
            msi.MsiEnumProductsW.restype = wintypes.UINT
            msi.MsiGetProductInfoW.argtypes = [
                wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPWSTR,
                ctypes.POINTER(wintypes.DWORD),
            ]
            msi.MsiGetProductInfoW.restype = wintypes.UINT
        except OSError:
            return []

        items: List[RawDiscoveryItem] = []
        for product_code in self._enum_products(msi):
            info = self._product_info(msi, product_code)
            name = info.get("ProductName") or ""
            if not name:
                name = product_code

            code_clean = product_code.strip("{}").upper()
            uninstall = "MsiExec.exe /X%s" % code_clean
            quiet = "MsiExec.exe /X%s /qn" % code_clean

            assignment = info.get("AssignmentType") or ""
            assignment_text = "per-machine" if assignment == "1" else "per-user"

            item = RawDiscoveryItem(
                id=make_id("msi", product_code),
                name=name,
                version=info.get("VersionString") or "",
                publisher=info.get("Publisher") or "",
                install_location=info.get("InstallLocation") or "",
                uninstall_string=uninstall,
                quiet_uninstall_string=quiet,
                install_date=info.get("InstallDate") or "",
                source=SOURCE_MSI,
                installer_type="msi",
                product_code=code_clean,
            )
            item.extra.update({
                "local_package": info.get("LocalPackage") or "",
                "package_code": info.get("PackageCode") or "",
                "assignment_type": assignment_text,
                "uninstall_command_source": "synthesized",
            })
            items.append(item)
        return items

    @staticmethod
    def _enum_products(msi) -> List[str]:
        codes: List[str] = []
        index = 0
        while True:
            buffer = ctypes.create_unicode_buffer(39)  # "{GUID}" + NUL
            result = msi.MsiEnumProductsW(index, buffer)
            if result == 0:
                codes.append(buffer.value)
                index += 1
            elif result == _ERROR_NO_MORE_ITEMS:
                break
            else:
                break
        return codes

    @staticmethod
    def _product_info(msi, product_code: str) -> dict:
        info = {}
        for prop in _PROPERTIES:
            buffer = ctypes.create_unicode_buffer(4096)
            size = wintypes.DWORD(len(buffer))
            result = msi.MsiGetProductInfoW(product_code, prop, buffer,
                                            ctypes.byref(size))
            info[prop] = buffer.value if result == 0 else ""
        return info
