"""DiscoveryManager: orchestrates the scanners and the pipeline.

Pipeline:

    RegistryScanner ─┐
    MsiScanner       ─┤
    AppxScanner      ─┤                        ┌─ FileMetadataScanner
    ServiceScanner   ─┼─► Normalizer ─► Dedup ─┼─ SignatureScanner
    StartupScanner   ─┤                        └─ launch-path resolver
    ScheduledTask    ─┤
    ShortcutScanner  ─┘                        └─► ApplicationDatabase
    PortableScanner (optional)

Scanners run in parallel on a thread pool.  Each has its own timeout and a
cancellation token; a failing or timed-out scanner is logged and skipped —
it never aborts the run.  The whole pipeline is read-only.
"""

from __future__ import annotations

import concurrent.futures
import os
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .classification import ClassificationEngine
from .database import ApplicationDatabase
from .deduplication import DeduplicationEngine
from .models import Application, DiscoveryResult, RawDiscoveryItem
from .normalizer import Normalizer
from .scanners import (
    AppxScanner,
    FileMetadataScanner,
    MsiScanner,
    PortableScanner,
    RegistryScanner,
    ScheduledTaskScanner,
    ServiceScanner,
    ShortcutScanner,
    SignatureScanner,
    StartupScanner,
)
from .textutils import is_uninstaller_name, normalize_name


@dataclass
class DiscoveryOptions:
    """Tunables for a discovery run."""

    enable_portable: bool = False
    portable_folders: List[str] = field(default_factory=list)
    scanner_timeout: float = 40.0
    max_workers: int = 6
    include_signatures: bool = True
    include_pe_metadata: bool = True


class DiscoveryManager:
    def __init__(self, log: Optional[Callable[[str], None]] = None):
        self._log = log or (lambda message: None)

    # ------------------------------------------------------------------ #
    def discover(self, options: Optional[DiscoveryOptions] = None,
                 cancel_event=None, on_log: Optional[Callable[[str], None]] = None) -> DiscoveryResult:
        opts = options or DiscoveryOptions()
        log = on_log or self._log
        result = DiscoveryResult()
        started = time.time()

        log("Discovery started")

        scanners = self._build_scanners(opts)
        items = self._run_scanners(scanners, opts, cancel_event, log, result)

        log("Normalization started")
        items = Normalizer().normalize_all(items)
        log("Deduplication started")
        apps = DeduplicationEngine().deduplicate(items)
        log("Deduplication completed")

        classifier = ClassificationEngine()
        classifier.classify_all(apps)

        for app in apps:
            app.launch_path = self._resolve_launch(app)

        if opts.include_pe_metadata or opts.include_signatures:
            self._enrich(apps, opts, log)

        result.apps = sorted(apps, key=lambda a: (a.name or "").lower())
        result.elapsed_seconds = round(time.time() - started, 2)
        log("Final applications: %d" % len(result.apps))
        return result

    # ------------------------------------------------------------------ #
    def _build_scanners(self, opts: DiscoveryOptions) -> list:
        scanners = [
            RegistryScanner(),
            MsiScanner(),
            AppxScanner(),
            ServiceScanner(),
            StartupScanner(),
            ScheduledTaskScanner(),
            ShortcutScanner(),
        ]
        if opts.enable_portable:
            scanners.append(PortableScanner(opts.portable_folders))
        return scanners

    def _run_scanners(self, scanners, opts, cancel_event, log, result) -> List[RawDiscoveryItem]:
        items: List[RawDiscoveryItem] = []
        futures = {}

        with concurrent.futures.ThreadPoolExecutor(max_workers=opts.max_workers) as pool:
            for scanner in scanners:
                if cancel_event is not None and cancel_event.is_set():
                    log("%s scan skipped (cancelled)" % scanner.name)
                    continue
                log("%s scan started" % scanner.name)
                futures[pool.submit(scanner.scan)] = (scanner, time.time())

            for future, (scanner, submitted_at) in list(futures.items()):
                if cancel_event is not None and cancel_event.is_set():
                    future.cancel()
                    log("%s scan skipped (cancelled)" % scanner.name)
                    continue

                remaining = opts.scanner_timeout - (time.time() - submitted_at)
                if remaining <= 0:
                    future.cancel()
                    self._record_failure(result, log, scanner, "timed out")
                    continue

                try:
                    found = future.result(timeout=remaining)
                except concurrent.futures.TimeoutError:
                    future.cancel()
                    self._record_failure(result, log, scanner, "timed out")
                    continue
                except Exception as error:  # noqa: BLE001 - isolate any failure
                    self._record_failure(result, log, scanner, str(error))
                    continue

                items.extend(found)
                result.counts[scanner.name] = len(found)
                log("%s scan completed: %d entries" % (scanner.name, len(found)))

        return items

    @staticmethod
    def _record_failure(result, log, scanner, reason):
        message = "%s scan failed: %s" % (scanner.name, reason)
        log(message)
        result.errors.append(message)

    # ------------------------------------------------------------------ #
    def _resolve_launch(self, app: Application) -> str:
        if app.launch_path:
            return app.launch_path

        candidates: List[str] = []
        canonical_exe = app.extra.get("executable_path") or ""
        if _is_launchable_exe(canonical_exe):
            candidates.append(canonical_exe)

        for comp in app.components:
            path = comp.path or ""
            if _is_launchable_exe(path) and path not in candidates:
                candidates.append(path)

        if not candidates:
            return ""

        # Prefer the executable whose name matches the application name.
        name_key = normalize_name(app.name)
        for path in candidates:
            base_key = normalize_name(os.path.basename(path))
            if name_key and base_key and (name_key in base_key or base_key in name_key):
                return path
        return candidates[0]

    def _enrich(self, apps: List[Application], opts: DiscoveryOptions, log) -> None:
        targets = [a.launch_path for a in apps
                   if a.launch_path and not a.launch_path.lower().startswith("shell:")]

        pe_by_path = {}
        if opts.include_pe_metadata and targets:
            pe_by_path = FileMetadataScanner().scan(targets)

        sig_by_path = {}
        if opts.include_signatures and targets:
            sig_by_path = SignatureScanner().scan(targets)
            log("Signature scan completed: %d files" % len(sig_by_path))

        for app in apps:
            path = app.launch_path
            if not path or path.lower().startswith("shell:"):
                continue
            if path in pe_by_path:
                app.pe_info = pe_by_path[path]
                if app.architecture == "unknown":
                    app.architecture = app.pe_info.get("architecture") or "unknown"
                if not app.publisher:
                    app.publisher = app.pe_info.get("CompanyName") or ""
            if path in sig_by_path:
                app.signature = sig_by_path[path]


def _is_launchable_exe(path: str) -> bool:
    if not path:
        return False
    if not path.lower().endswith(".exe"):
        return False
    if is_uninstaller_name(path):
        return False
    try:
        return os.path.isfile(path)
    except OSError:
        return False
