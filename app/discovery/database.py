"""In-memory application database: stores and queries the final applications."""

from __future__ import annotations

from typing import List, Optional

from .models import Application


class ApplicationDatabase:
    def __init__(self, apps: Optional[List[Application]] = None):
        self._apps: List[Application] = list(apps or [])

    # ------------------------------------------------------------------ #
    def add(self, apps: List[Application]) -> None:
        self._apps.extend(apps)

    def all(self) -> List[Application]:
        return sorted(self._apps, key=lambda a: (a.name or "").lower())

    def surface(self) -> List[Application]:
        return [a for a in self.all() if a.surfaceable]

    def hidden(self) -> List[Application]:
        return [a for a in self.all() if not a.surfaceable]

    def by_id(self, app_id: str) -> Optional[Application]:
        for app in self._apps:
            if app.id == app_id:
                return app
        return None

    def search(self, query: str, include_hidden: bool = False) -> List[Application]:
        needle = (query or "").strip().lower()
        apps = self.all() if include_hidden else self.surface()
        if not needle:
            return apps
        return [a for a in apps
                if needle in self._haystack(a)]

    @staticmethod
    def _haystack(app: Application) -> str:
        return " ".join([
            app.name, app.publisher, app.version, app.install_location,
            app.classification, " ".join(app.sources),
        ]).lower()

    def to_dicts(self, include_hidden: bool = False) -> List[dict]:
        apps = self.all() if include_hidden else self.surface()
        return [a.to_dict() for a in apps]
