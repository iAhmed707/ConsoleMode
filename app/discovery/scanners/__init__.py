"""Scanners for the Installed Programs Discovery Engine.

Each scanner subclasses :class:`BaseScanner` and returns a list of
:class:`RawDiscoveryItem`.  Scanners are independent, read-only, and must be
safe to run on a background thread.
"""

from .base import BaseScanner
from .registry_scanner import RegistryScanner
from .msi_scanner import MsiScanner
from .appx_scanner import AppxScanner
from .service_scanner import ServiceScanner
from .startup_scanner import StartupScanner
from .scheduled_task_scanner import ScheduledTaskScanner
from .shortcut_scanner import ShortcutScanner
from .portable_scanner import PortableScanner
from .file_metadata_scanner import FileMetadataScanner
from .signature_scanner import SignatureScanner

__all__ = [
    "BaseScanner",
    "RegistryScanner",
    "MsiScanner",
    "AppxScanner",
    "ServiceScanner",
    "StartupScanner",
    "ScheduledTaskScanner",
    "ShortcutScanner",
    "PortableScanner",
    "FileMetadataScanner",
    "SignatureScanner",
]
