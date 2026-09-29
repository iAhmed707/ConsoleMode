"""Installed Programs Discovery Engine (Revo Uninstaller-style, read-only).

Public entry points:

* :class:`~app.discovery.engine.DiscoveryManager` — run the full pipeline,
* :func:`discover` — one-call convenience wrapper.

Everything is read-only: no registry keys are deleted, no services are
stopped, no uninstallers are run.
"""

from .engine import DiscoveryManager, DiscoveryOptions
from .models import (
    Application,
    Component,
    DiscoveryResult,
    RawDiscoveryItem,
)
from .database import ApplicationDatabase


def discover(options=None, on_log=None, cancel_event=None):
    """Run a discovery and return a :class:`DiscoveryResult`."""
    manager = DiscoveryManager(on_log)
    return manager.discover(options=options, cancel_event=cancel_event)


__all__ = [
    "DiscoveryManager",
    "DiscoveryOptions",
    "Application",
    "ApplicationDatabase",
    "Component",
    "DiscoveryResult",
    "RawDiscoveryItem",
    "discover",
]
