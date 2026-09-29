"""Base scanner contract and shared id helpers."""

from __future__ import annotations

import hashlib
from typing import List

from ..models import RawDiscoveryItem


def make_id(prefix: str, *parts: str) -> str:
    """Build a stable, collision-resistant item id from ``prefix`` + parts.

    The id is deterministic across runs so caching/dedup behave consistently,
    and it is content-addressed so two scanners describing the same entity
    (e.g. a GUID seen in both registry views) never collide accidentally.
    """
    joined = "|".join(str(part) for part in parts)
    digest = hashlib.sha1(joined.encode("utf-8", errors="replace")).hexdigest()[:12]
    return "%s:%s" % (prefix, digest)


class BaseScanner:
    """Common interface for every scanner."""

    #: Short, human-readable scanner name used in logs and counts.
    name = "base"

    def scan(self) -> List[RawDiscoveryItem]:
        """Perform the (read-only) scan and return raw items.

        Subclasses must never raise for *expected* failures (missing COM,
        missing elevation, ...); they return an empty list instead.  An
        unexpected exception is caught by the engine and logged, so a single
        failing scanner cannot take the whole discovery down.
        """
        raise NotImplementedError
