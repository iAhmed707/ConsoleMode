"""Portable Executable (PE) metadata extraction.

Reads two things from a Windows ``.exe``/``.dll``:

1. **Architecture** from the COFF header ``IMAGE_FILE_MACHINE`` word.  This is
   parsed directly from the file bytes (``struct``), so it needs no API and
   works for any PE file, signed or not.

2. **Version / company / product strings** from the version resource via the
   official Win32 APIs ``GetFileVersionInfoSizeW`` / ``GetFileVersionInfoW`` /
   ``VerQueryValueW`` in ``version.dll`` (exposed through ``ctypes``).  These
   are the same APIs ``Get-Item .VersionInfo`` uses.

All functions are read-only and never load the PE into memory as a module.
"""

from __future__ import annotations

import os
import struct
from typing import Any, Dict, Optional

from .models import machine_to_arch

# IMAGE_DOS_HEADER e_lfanew lives at offset 0x3C as a 32-bit LE integer.
_E_LFANEW_OFFSET = 0x3C

# Version-resource string keys we care about.
_VERSION_KEYS = (
    "CompanyName",
    "ProductName",
    "FileDescription",
    "FileVersion",
    "ProductVersion",
    "OriginalFilename",
    "LegalCopyright",
)


def read_architecture(path: str) -> str:
    """Return the PE architecture (``x86``/``x64``/``arm64``/...) of ``path``.

    Returns ``models.ARCH_UNKNOWN`` for anything that is not a readable PE
    image (text files, missing files, ...).
    """
    try:
        with open(path, "rb") as handle:
            header = handle.read(0x1000)  # DOS + COFF headers are tiny
    except OSError:
        return "unknown"

    if len(header) < _E_LFANEW_OFFSET + 4:
        return "unknown"

    (e_lfanew,) = struct.unpack_from("<I", header, _E_LFANEW_OFFSET)
    # PE signature is "PE\0\0"; the COFF header follows immediately.
    coff = e_lfanew + 4
    if coff + 4 > len(header) or header[e_lfanew:e_lfanew + 4] != b"PE\x00\x00":
        return "unknown"

    (machine,) = struct.unpack_from("<H", header, coff)
    return machine_to_arch(machine)


def read_version_info(path: str) -> Dict[str, str]:
    """Extract version-resource strings using ``version.dll``.

    Returns a dict keyed by ``CompanyName``, ``ProductName``, ... with values
    normalised to stripped strings.  Files without a version resource yield an
    empty dict.
    """
    if not os.path.isfile(path):
        return {}

    try:
        import ctypes
        from ctypes import wintypes

        version_dll = ctypes.WinDLL("version.dll", use_last_error=True)

        version_dll.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p]
        version_dll.GetFileVersionInfoSizeW.restype = wintypes.DWORD

        version_dll.GetFileVersionInfoW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        ]
        version_dll.GetFileVersionInfoW.restype = wintypes.BOOL

        version_dll.VerQueryValueW.argtypes = [
            wintypes.LPCVOID, wintypes.LPCWSTR,
            ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT),
        ]
        version_dll.VerQueryValueW.restype = wintypes.BOOL
    except OSError:
        return {}

    size = version_dll.GetFileVersionInfoSizeW(path, None)
    if not size:
        return {}

    buffer = ctypes.create_string_buffer(size)
    if not version_dll.GetFileVersionInfoW(path, 0, size, buffer):
        return {}

    # The translation table tells us which language/codepage pairs exist; the
    # strings are addressed as \StringFileInfo\<lang><codepage>\<Key>.
    ptr = ctypes.c_void_p()
    length = wintypes.UINT()
    if not version_dll.VerQueryValueW(buffer, r"\VarFileInfo\Translation",
                                      ctypes.byref(ptr), ctypes.byref(length)):
        return {}

    # The translation table is an array of (WORD lang, WORD codepage) pairs;
    # read the raw bytes the returned pointer addresses.
    translation_bytes = ctypes.string_at(ptr.value, length.value)
    translations = []
    count = length.value // 4
    for index in range(count):
        lang, codepage = struct.unpack_from("<HH", translation_bytes, index * 4)
        translations.append((lang, codepage))

    result: Dict[str, str] = {}
    for lang, codepage in translations:
        for key in _VERSION_KEYS:
            sub_block = r"\StringFileInfo\%04x%04x\%s" % (lang, codepage, key)
            ptr = ctypes.c_void_p()
            length = wintypes.UINT()
            if version_dll.VerQueryValueW(buffer, sub_block, ctypes.byref(ptr),
                                          ctypes.byref(length)):
                try:
                    # puLen is the length in characters (including the NUL).
                    value = ctypes.wstring_at(ptr.value, length.value - 1)
                except (ValueError, OSError):
                    continue
                value = value.strip()
                if value:
                    result.setdefault(key, value)
        if result:
            break  # first translation that produced strings wins

    return result


def get_pe_info(path: str) -> Dict[str, Any]:
    """Combine architecture + version info for ``path`` in one dict."""
    info: Dict[str, Any] = {
        "path": path,
        "architecture": read_architecture(path),
        "exists": os.path.isfile(path),
        "size": _file_size(path),
    }
    info.update(read_version_info(path))
    return info


def _file_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0
