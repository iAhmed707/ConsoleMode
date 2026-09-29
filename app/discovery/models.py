"""Data models for the Installed Programs Discovery Engine.

Every scanner emits :class:`RawDiscoveryItem` objects.  The normalizer cleans
them up, the deduplication engine merges them into :class:`Application`
objects, and the classification engine labels each application.  All models
are plain dataclasses so they serialise to JSON for logging, tests and the UI.

The engine is strictly read-only: these objects only *describe* programs and
never carry out an uninstall or a registry/file mutation.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------- #
# Source types (where a discovery item came from)
# --------------------------------------------------------------------------- #
SOURCE_REGISTRY = "Registry"
SOURCE_MSI = "MSI"
SOURCE_APPX = "AppX"
SOURCE_MSIX = "MSIX"
SOURCE_SERVICE = "Service"
SOURCE_STARTUP = "Startup"
SOURCE_SCHEDULED_TASK = "ScheduledTask"
SOURCE_SHORTCUT = "Shortcut"
SOURCE_PORTABLE = "Portable"

# Sources that *define* an installed program.  Component sources (Service,
# Startup, ScheduledTask, Shortcut) are metadata that usually attaches to a
# program found in a primary source rather than standing alone.
PRIMARY_SOURCES = frozenset({SOURCE_REGISTRY, SOURCE_MSI, SOURCE_APPX, SOURCE_MSIX, SOURCE_PORTABLE})
COMPONENT_SOURCES = frozenset({
    SOURCE_SERVICE, SOURCE_STARTUP, SOURCE_SCHEDULED_TASK, SOURCE_SHORTCUT,
})

# --------------------------------------------------------------------------- #
# Classifications
# --------------------------------------------------------------------------- #
CLASS_NORMAL = "Normal Application"
CLASS_SYSTEM = "System Component"
CLASS_UPDATE = "Update"
CLASS_RUNTIME = "Runtime"
CLASS_DRIVER = "Driver"
CLASS_FRAMEWORK = "Framework"
CLASS_LANGUAGE_PACK = "Language Pack"
CLASS_UNKNOWN = "Unknown"

# Classifications that are hidden from the default "installed apps" list
# (Revo-style: they are noise, not programs the user launches).  Frameworks are
# hidden too — "do not show frameworks and internal components as ordinary
# programs unless there is a clear reason".
NON_SURFACE_CLASSES = frozenset({
    CLASS_SYSTEM, CLASS_UPDATE, CLASS_DRIVER, CLASS_LANGUAGE_PACK, CLASS_FRAMEWORK,
})

# --------------------------------------------------------------------------- #
# Architectures
# --------------------------------------------------------------------------- #
ARCH_X86 = "x86"
ARCH_X64 = "x64"
ARCH_ARM64 = "arm64"
ARCH_ARM = "arm"
ARCH_IA64 = "ia64"
ARCH_NEUTRAL = "neutral"
ARCH_UNKNOWN = "unknown"

# PE IMAGE_FILE_MACHINE constants (little-endian words at the COFF header).
_MACHINE_ARCH = {
    0x014C: ARCH_X86,
    0x8664: ARCH_X64,
    0xAA64: ARCH_ARM64,
    0x01C0: ARCH_ARM,
    0x01C4: ARCH_ARM,
    0x0200: ARCH_IA64,
}


def machine_to_arch(machine: int) -> str:
    """Map a PE ``IMAGE_FILE_MACHINE`` value to a friendly architecture name."""
    return _MACHINE_ARCH.get(machine, ARCH_UNKNOWN)


# --------------------------------------------------------------------------- #
# Components
# --------------------------------------------------------------------------- #
@dataclass
class Component:
    """A related artifact of an application (service, startup entry, ...).

    ``kind`` is one of ``executable``, ``service``, ``startup``,
    ``scheduled_task``, ``shortcut``, ``package``.
    """

    kind: str
    path: Optional[str] = None
    name: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Raw discovery item
# --------------------------------------------------------------------------- #
@dataclass
class RawDiscoveryItem:
    """One un-merged finding from a scanner.

    Field names deliberately mirror the registry value names (DisplayName,
    UninstallString, ...) so the registry scanner maps one-to-one.
    """

    id: str
    name: str = ""
    version: str = ""
    publisher: str = ""
    install_location: str = ""
    uninstall_string: str = ""
    quiet_uninstall_string: str = ""
    display_icon: str = ""
    install_date: str = ""
    estimated_size: int = 0

    source: str = ""
    architecture: str = ARCH_UNKNOWN
    installer_type: str = ""          # "msi" | "exe" | "appx" | "msix" | "service" | ""
    product_code: str = ""
    package_full_name: str = ""
    package_family_name: str = ""
    app_user_model_id: str = ""
    is_framework: bool = False
    is_resource: bool = False
    package_type: str = ""            # "app" | "framework" | "resource"
    executable_path: str = ""

    # Registry flags that influence classification (SystemComponent, ...).
    flags: Dict[str, Any] = field(default_factory=dict)

    # Related artifacts discovered by the same scanner (services, files, ...).
    components: List[Component] = field(default_factory=list)

    # Anything scanner-specific (description, state, signature, ...).
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Final application
# --------------------------------------------------------------------------- #
@dataclass
class Application:
    """A deduplicated, classified program ready for the UI."""

    id: str
    name: str = ""
    version: str = ""
    publisher: str = ""
    install_location: str = ""
    uninstall_command: str = ""
    quiet_uninstall_command: str = ""

    # Best executable to *launch* the program (a filesystem path, or a
    # ``shell:AppsFolder\\<AUMID>`` target for Store apps).
    launch_path: str = ""

    source: str = ""                  # primary (highest-priority) source
    architecture: str = ARCH_UNKNOWN
    installer_type: str = ""
    classification: str = CLASS_UNKNOWN
    confidence: float = 0.0

    product_code: str = ""
    package_full_name: str = ""
    app_user_model_id: str = ""

    components: List[Component] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)   # every contributing source
    signature: Dict[str, Any] = field(default_factory=dict)
    pe_info: Dict[str, Any] = field(default_factory=dict)
    extra: Dict[str, Any] = field(default_factory=dict)

    # Whether this entry should appear in the default list.  Component-only
    # findings (a service with no owning program) and non-surface classes are
    # hidden unless the user opts in.
    surfaceable: bool = True

    @property
    def launchable(self) -> bool:
        """Whether we have something the profile launcher can start."""
        return bool(self.launch_path)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Discovery result
# --------------------------------------------------------------------------- #
@dataclass
class DiscoveryResult:
    """The outcome of a full discovery run."""

    apps: List[Application] = field(default_factory=list)
    logs: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    counts: Dict[str, int] = field(default_factory=dict)   # scanner -> items found
    elapsed_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "apps": [a.to_dict() for a in self.apps],
            "logs": self.logs,
            "errors": self.errors,
            "counts": self.counts,
            "elapsed_seconds": self.elapsed_seconds,
        }
