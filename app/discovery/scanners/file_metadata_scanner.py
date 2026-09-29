"""PE metadata enricher (architecture + version info) for a batch of files.

Not a source scanner: it does not produce ``RawDiscoveryItem`` objects.  It is
run *after* deduplication on the resolved main executable of each application
so the UI can show the architecture and the real ``CompanyName`` /
``FileVersion`` even when the registry was silent.
"""

from __future__ import annotations

from typing import Dict, Iterable

from .. import pe
from .base import BaseScanner


class FileMetadataScanner(BaseScanner):
    name = "FileMetadata"

    def __init__(self):
        self._cache: Dict[str, dict] = {}

    def scan(self, paths: Iterable[str]) -> Dict[str, dict]:
        """Return ``{path: pe_info}`` for the given executable paths."""
        result: Dict[str, dict] = {}
        for path in paths:
            if not path or path.lower().startswith("shell:"):
                continue
            if path not in self._cache:
                self._cache[path] = pe.get_pe_info(path)
            result[path] = self._cache[path]
        return result
