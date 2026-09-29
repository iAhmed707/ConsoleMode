"""Application classification layer.

Labels every merged :class:`Application` as one of:

    Normal Application | System Component | Update | Runtime | Driver |
    Framework | Language Pack | Unknown

and decides whether it should appear in the default list.  The ordering of the
rules matters: a Microsoft "KB..." entry is an Update even though it is also a
system component, etc.
"""

from __future__ import annotations

import re
from typing import List

from .models import (
    Application,
    CLASS_DRIVER,
    CLASS_FRAMEWORK,
    CLASS_LANGUAGE_PACK,
    CLASS_NORMAL,
    CLASS_RUNTIME,
    CLASS_SYSTEM,
    CLASS_UNKNOWN,
    CLASS_UPDATE,
    NON_SURFACE_CLASSES,
)

_KB_RE = re.compile(r"\bkb\d{5,}\b", re.IGNORECASE)

_LANG_RE = re.compile(r"language[\s_-]?pack", re.IGNORECASE)

_FRAMEWORK_RE = re.compile(
    r"\.net\s+framework|framework\b|\bsdk\b|\bredistributable\s+framework",
    re.IGNORECASE,
)
_RUNTIME_RE = re.compile(
    r"\bruntime\b|redistributable|visual\s*c\+\+|vc\+\+|vcredist|"
    r"\.net\s+runtime|\.net\s+sdk|\bjre\b|\bjava\b|directx|webview2|"
    r"\bopenal\b|\bphysx\b|\bxna\b",
    re.IGNORECASE,
)

_UPDATE_NAME_PREFIXES = (
    "update for ",
    "security update for ",
    "hotfix for ",
    "hotfix ",
    "service pack ",
)

_UPDATE_RELEASE = {"update", "security update", "hotfix", "service pack"}


class ClassificationEngine:
    def classify_all(self, apps: List[Application]) -> List[Application]:
        for app in apps:
            self.classify(app)
        return apps

    def classify(self, app: Application) -> str:
        name = (app.name or "").lower()
        flags = app.extra.get("flags") or {}
        release = ((flags.get("ReleaseType") or "").strip().lower())
        parent = ((flags.get("ParentKeyName") or "").strip() or
                  (flags.get("ParentDisplayName") or "").strip())
        system_component = bool(flags.get("SystemComponent"))
        is_framework = bool(app.extra.get("is_framework"))
        is_resource = bool(app.extra.get("is_resource"))
        package_type = (app.extra.get("package_type") or "").lower()
        is_driver = bool(app.extra.get("is_driver"))
        location = (app.install_location or "").lower()
        executable = (app.extra.get("executable_path") or "").lower()

        classification = self._classify(
            name, release, parent, system_component, is_framework, is_resource,
            package_type, is_driver, location, executable,
        )

        app.classification = classification
        if classification in NON_SURFACE_CLASSES:
            app.surfaceable = False
        # Otherwise keep the dedup layer's decision (component-only findings
        # stay hidden even when they classify as "Normal").
        return classification

    def _classify(self, name, release, parent, system_component, is_framework,
                  is_resource, package_type, is_driver, location, executable):
        # 1. Drivers.
        if (is_driver
                or "\bdriver\b" in name or name.rstrip().endswith(" driver")
                or "\\drivers\\" in location
                or executable.endswith(".sys")):
            return CLASS_DRIVER

        # 2. Language packs.
        if _LANG_RE.search(name) or release == "language pack":
            return CLASS_LANGUAGE_PACK

        # 3. Updates / hotfixes / service packs.
        if (system_component or parent
                or release in _UPDATE_RELEASE
                or _KB_RE.search(name)
                or name.startswith(_UPDATE_NAME_PREFIXES)):
            return CLASS_UPDATE

        # 4. Frameworks (including AppX framework packages and SDKs).
        if is_framework or package_type == "framework" or _FRAMEWORK_RE.search(name):
            return CLASS_FRAMEWORK

        # 5. Runtimes / redistributables.
        if _RUNTIME_RE.search(name):
            return CLASS_RUNTIME

        # 6. Remaining system / resource components.
        if is_resource or package_type == "resource":
            return CLASS_SYSTEM
        if location.startswith("c:\\windows") or "\\system32" in executable:
            return CLASS_SYSTEM

        # 7. A name and some uninstall/identity signal is a normal app.
        if name:
            return CLASS_NORMAL
        return CLASS_UNKNOWN
