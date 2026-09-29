"""String normalisation helpers shared by the normalizer, dedup and classifier.

These are deliberately small and deterministic: the matching engine relies on
them producing stable keys for names, versions and GUIDs.
"""

from __future__ import annotations

import re
from typing import Optional

_GUID_RE = re.compile(
    r"^[{(]?([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})[)}]?$"
)

_UNINSTALLER_TOKENS = (
    "unins", "uninstall", "setup", "install", "updater", "update", "stub",
    "repair", "unins000",
)


def looks_like_guid(value: str) -> bool:
    return bool(value) and bool(_GUID_RE.match(str(value).strip()))


def normalize_guid(value: Optional[str]) -> str:
    """Canonical GUID: uppercase, braces stripped; ``""`` if not a GUID."""
    if not value:
        return ""
    match = _GUID_RE.match(str(value).strip())
    return match.group(1).upper() if match else ""


def normalize_name(value: Optional[str]) -> str:
    """A token-normalised name for fuzzy comparison.

    Lowercases, drops architecture suffixes and a trailing dotted version,
    then collapses everything non-alphanumeric to single spaces.  This is a
    *matching key*, not a display value.
    """
    if not value:
        return ""
    text = str(value).lower()
    text = re.sub(r"\s*\(x(86|64)\)", " ", text)
    text = re.sub(r"\s*-\s*(x(86|64)|x86|x64)\s*$", " ", text)
    # Trailing dotted version ("... 1.2.3") — but not a bare "Windows 11".
    text = re.sub(r"\s+\d+(\.\d+){1,}\s*$", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def normalize_version(value: Optional[str]) -> str:
    if not value:
        return ""
    text = str(value).strip()
    text = re.sub(r"^[vV]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_path(value: Optional[str]) -> str:
    """Canonical path for comparison: expanded, lowered, trailing slash off."""
    if not value:
        return ""
    import os
    try:
        text = os.path.expandvars(str(value))
    except (ValueError, OSError):
        text = str(value)
    text = text.strip().strip('"')
    text = text.replace("/", "\\")
    return text.rstrip("\\").lower()


def is_uninstaller_name(path: Optional[str]) -> bool:
    """Heuristic: does this filename look like an installer/uninstaller?"""
    if not path:
        return True
    import os
    base = os.path.basename(str(path)).lower()
    if base.endswith(".exe"):
        base = base[:-4]
    return any(token in base for token in _UNINSTALLER_TOKENS)
