"""Deduplication / matching engine.

The same program can arrive from Registry + MSI + AppX + Service + Shortcut
simultaneously.  This module scores pairs of :class:`RawDiscoveryItem` and
merges those that clearly describe the same program into a single
:class:`Application`.

Matching is **not** name-only.  The scoring follows the design spec:

+100  ProductCode equal
+ 90  InstallLocation equal (normalised)
+ 80  UninstallString points at the same executable
+ 70  executable path equal
+ 50  Publisher equal (normalised)
+ 40  Product name similar (normalised equality / token ratio)
+ 30  Version compatible

Merge thresholds:

>= 80   merge (high confidence)
60-79   candidate — merge only if additional review rules also pass
< 60   never merge automatically

Fuzzy name similarity is a weak signal on purpose, so two different programs
that merely share a word are not merged.
"""

from __future__ import annotations

import os
from typing import List, Optional

from .models import (
    Application,
    Component,
    RawDiscoveryItem,
)
from .textutils import (
    normalize_guid,
    normalize_name,
    normalize_path,
    normalize_version,
)

# Source priority for picking the canonical item of a cluster (higher wins).
_SOURCE_PRIORITY = {
    "Registry": 50,
    "MSI": 40,
    "AppX": 30,
    "MSIX": 30,
    "Portable": 20,
    "Service": 10,
    "Startup": 10,
    "ScheduledTask": 10,
    "Shortcut": 10,
}

_MERGE_THRESHOLD = 80
_REVIEW_LOW = 60


def _norm(item: RawDiscoveryItem, key: str, raw_field: str = ""):
    """Read a normalised value cached by the Normalizer, else compute it."""
    value = item.extra.get(key)
    if value is not None:
        return value
    if not raw_field:
        return ""
    return normalize_path(getattr(item, raw_field, "") or "")


def name_similarity(a: str, b: str) -> float:
    """0..1 similarity between two *already-normalised* names.

    Token-based (Jaccard) rather than char-level: "Google Chrome" and "Google
    Drive" share the vendor token but are different programs, so char-level
    ``difflib`` would over-score them.  A subset relation (e.g. "Chrome" vs
    "Google Chrome") is treated as a strong match.
    """
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0

    ta = set(a.split())
    tb = set(b.split())
    if not ta or not tb:
        return 0.0

    inter = len(ta & tb)
    union = len(ta | tb)
    jaccard = inter / union
    if ta <= tb or tb <= ta:
        return max(0.85, jaccard)
    return jaccard


def _name_similarity_gated(a: RawDiscoveryItem, b: RawDiscoveryItem) -> float:
    """Name similarity, but skip the expensive fuzzy compare when the two
    names share no token at all (they clearly describe different programs)."""
    na = a.extra.get("normalized_name") or ""
    nb = b.extra.get("normalized_name") or ""
    if not na or not nb:
        return 0.0

    ta = a.extra.get("name_tokens")
    tb = b.extra.get("name_tokens")
    if ta is not None and tb is not None and not (ta & tb):
        return 0.0
    return name_similarity(na, nb)


def versions_compatible(a: str, b: str) -> bool:
    # Absent version info is *not* evidence of sameness, so two empty versions
    # contribute nothing.  Only matching (or prefix-matching) real versions add
    # the +30 signal.
    if not a or not b:
        return False
    a = normalize_version(a)
    b = normalize_version(b)
    return a == b or a.startswith(b) or b.startswith(a)


def score_pair(a: RawDiscoveryItem, b: RawDiscoveryItem) -> int:
    score = 0

    pc_a = a.extra.get("normalized_product_code") or normalize_guid(a.product_code)
    pc_b = b.extra.get("normalized_product_code") or normalize_guid(b.product_code)
    if pc_a and pc_b and pc_a == pc_b:
        score += 100

    la = _norm(a, "normalized_location", "install_location")
    lb = _norm(b, "normalized_location", "install_location")
    if la and lb and la == lb:
        score += 90

    ua = a.extra.get("normalized_uninstall_exe") or ""
    ub = b.extra.get("normalized_uninstall_exe") or ""
    if ua and ub and ua == ub:
        score += 80

    ea = _norm(a, "normalized_executable", "executable_path")
    eb = _norm(b, "normalized_executable", "executable_path")
    if ea and eb and ea == eb:
        score += 70

    pa = a.extra.get("normalized_publisher") or ""
    pb = b.extra.get("normalized_publisher") or ""
    if pa and pb and pa == pb:
        score += 50

    sim = _name_similarity_gated(a, b)
    if sim >= 0.9:
        score += 40
    elif sim >= 0.8:
        score += 25
    elif sim >= 0.6:
        score += 15

    if versions_compatible(a.version, b.version):
        score += 30

    return score


def _review_pass(a: RawDiscoveryItem, b: RawDiscoveryItem, sim: float) -> bool:
    """Extra evidence required to merge a 60-79 'possible match'."""
    pa = a.extra.get("normalized_publisher")
    pb = b.extra.get("normalized_publisher")
    la = a.extra.get("normalized_location")
    lb = b.extra.get("normalized_location")

    if pa and pb and pa == pb and sim >= 0.8:
        return True
    if la and lb and la == lb:
        return True
    ua = a.extra.get("normalized_uninstall_exe") or ""
    ub = b.extra.get("normalized_uninstall_exe") or ""
    if ua and ub and ua == ub:
        return True
    return False


class DeduplicationEngine:
    def deduplicate(self, items: List[RawDiscoveryItem]) -> List[Application]:
        clusters: List[List[RawDiscoveryItem]] = []
        for item in items:
            best_cluster: Optional[List[RawDiscoveryItem]] = None
            best_score = 0
            best_sim = 0.0
            best_other: Optional[RawDiscoveryItem] = None

            for cluster in clusters:
                for other in cluster:
                    s = score_pair(item, other)
                    if s > best_score:
                        best_score = s
                        best_cluster = cluster
                        best_sim = name_similarity(
                            item.extra.get("normalized_name", ""),
                            other.extra.get("normalized_name", ""),
                        )
                        best_other = other

            if best_cluster is None:
                clusters.append([item])
            elif best_score >= _MERGE_THRESHOLD:
                best_cluster.append(item)
            elif best_score >= _REVIEW_LOW and best_other is not None and _review_pass(item, best_other, best_sim):
                best_cluster.append(item)
            else:
                clusters.append([item])

        return [build_application(cluster, index)
                for index, cluster in enumerate(clusters)]


def build_application(cluster: List[RawDiscoveryItem], index: int = 0) -> Application:
    """Merge a cluster of raw items into one :class:`Application`."""
    canonical = _canonical(cluster)

    app = Application(id="app-%d" % index)
    app.name = _first_nonempty(cluster, "name")
    app.version = _first_nonempty(cluster, "version")
    app.publisher = _first_nonempty(cluster, "publisher")
    app.install_location = _first_nonempty(cluster, "install_location")
    app.uninstall_command = _first_nonempty(cluster, "uninstall_string")
    app.quiet_uninstall_command = _first_nonempty(cluster, "quiet_uninstall_string")
    app.product_code = _first_nonempty(cluster, "product_code")
    app.package_full_name = _first_nonempty(cluster, "package_full_name")
    app.app_user_model_id = _first_nonempty(cluster, "app_user_model_id")
    app.launch_path = _first_nonempty(cluster, "launch_path")
    app.source = canonical.source
    app.architecture = canonical.architecture
    app.installer_type = _first_nonempty(cluster, "installer_type")

    app.sources = _unique_sources(cluster)
    app.components = _merge_components(cluster)

    # Aggregate flags and package facts for the classifier.
    merged_flags = {}
    is_framework = False
    is_resource = False
    package_type = ""
    is_driver = False
    for item in cluster:
        merged_flags.update(item.flags)
        is_framework = is_framework or bool(item.is_framework)
        is_resource = is_resource or bool(item.is_resource)
        package_type = package_type or item.package_type
        is_driver = is_driver or bool(item.extra.get("is_driver"))

    app.extra.update({
        "flags": merged_flags,
        "is_framework": is_framework,
        "is_resource": is_resource,
        "package_type": package_type,
        "is_driver": is_driver,
        "executable_path": _first_nonempty(cluster, "executable_path"),
        "primary_source": canonical.source,
    })

    app.surfaceable = any(
        item.source in _primary_source_names() for item in cluster
    )
    app.confidence = _confidence(app)
    return app


def _primary_source_names():
    from .models import PRIMARY_SOURCES
    return PRIMARY_SOURCES


def _canonical(cluster: List[RawDiscoveryItem]) -> RawDiscoveryItem:
    """The best representative: highest-priority source, then most detail."""
    def key(item: RawDiscoveryItem):
        priority = _SOURCE_PRIORITY.get(item.source, 0)
        completeness = (bool(item.name) + bool(item.version) +
                        bool(item.publisher) + bool(item.install_location))
        return (priority, completeness, item.estimated_size or 0)
    return max(cluster, key=key)


def _first_nonempty(cluster: List[RawDiscoveryItem], field: str) -> str:
    for item in cluster:
        value = getattr(item, field, "")
        if value:
            return value
    return ""


def _unique_sources(cluster: List[RawDiscoveryItem]) -> List[str]:
    seen = []
    for item in cluster:
        if item.source and item.source not in seen:
            seen.append(item.source)
    return seen


def _merge_components(cluster: List[RawDiscoveryItem]) -> List[Component]:
    seen = set()
    merged: List[Component] = []
    for item in cluster:
        for comp in item.components:
            key = (comp.kind, (comp.name or "").lower(), (comp.path or "").lower())
            if key not in seen:
                seen.add(key)
                merged.append(comp)
    return merged


def _confidence(app: Application) -> float:
    """A discovery-confidence estimate, capped at 95% (never 100%).

    Multiple independent sources agreeing is the strongest signal; a single
    source is still shown but at a lower confidence.
    """
    count = len(app.sources)
    value = 55 + 10 * count
    return float(min(95, value))
