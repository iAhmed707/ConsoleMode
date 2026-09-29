"""Dialog for picking installed applications to add to a profile.

Presents a Revo Uninstaller-style table (name, version, publisher, location,
installer type, architecture, confidence) with a search box, a toggle to show
updates/system components, and an on-demand "Details" panel that lists the
sources, components, classification and Authenticode signature.

The dialog is read-only: it only returns the launch path of the selected rows.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
)

COLUMNS = ["Application", "Version", "Publisher", "Location", "Type", "Arch", "Conf."]


class InstalledAppsDialog(QDialog):
    """Searchable, detailed list of installed applications."""

    def __init__(self, apps, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add installed application")
        self.resize(1020, 620)
        self._apps = apps

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        heading = QLabel("Choose one or more installed applications")
        heading.setFont(QFont("Segoe UI", 14, QFont.Bold))
        layout.addWidget(heading)

        # --- search / filters -------------------------------------------
        controls = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by name, publisher or location…")
        self.search.textChanged.connect(self._apply_filter)
        controls.addWidget(self.search, 1)

        self.show_all_check = QCheckBox("Show updates & system components")
        self.show_all_check.toggled.connect(self._apply_filter)
        controls.addWidget(self.show_all_check)
        layout.addLayout(controls)

        # --- table --------------------------------------------------------
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideRight)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.itemSelectionChanged.connect(self._update_details)
        layout.addWidget(self.table, 1)

        # --- details panel (on demand) -----------------------------------
        self.details_btn = QPushButton("Details")
        self.details_btn.setCheckable(True)
        self.details_btn.toggled.connect(self._toggle_details)
        layout.addWidget(self.details_btn)

        self.details = QTextBrowser()
        self.details.setVisible(False)
        self.details.setStyleSheet(
            "QTextBrowser{background:#1A1B1E;border:1px solid #2F3033;"
            "border-radius:6px;color:#D1D5DB;padding:6px;}"
        )
        layout.addWidget(self.details)

        # --- footer --------------------------------------------------------
        footer = QHBoxLayout()
        self.count_label = QLabel("")
        self.count_label.setStyleSheet("color:#9CA3AF;")
        footer.addWidget(self.count_label)
        footer.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        footer.addWidget(cancel_btn)

        self.add_btn = QPushButton("Add selected")
        self.add_btn.setObjectName("LaunchButton")
        self.add_btn.clicked.connect(self.accept)
        self.add_btn.setEnabled(False)
        footer.addWidget(self.add_btn)
        layout.addLayout(footer)

        self._populate()
        self._update_buttons()

    # ------------------------------------------------------------------ #
    def _populate(self):
        self.table.setRowCount(len(self._apps))
        for row, app in enumerate(self._apps):
            name_item = QTableWidgetItem(app.get("name") or "")
            name_item.setData(Qt.UserRole, app)

            if not app.get("launchable"):
                name_item.setForeground(QColor("#6B7280"))
                name_item.setToolTip(
                    "No launch target was found for this entry, so it cannot "
                    "be added to a profile."
                )
            self.table.setItem(row, 0, name_item)

            self._set_text(row, 1, app.get("version") or "")
            self._set_text(row, 2, app.get("publisher") or "")
            self._set_text(row, 3, app.get("location") or "")
            self._set_text(row, 4, (app.get("installer_type") or "").upper())

            arch = app.get("architecture") or ""
            self._set_text(row, 5, arch, color="#93C5FD" if arch else None)

            conf = app.get("confidence")
            conf_text = ("%d%%" % int(round(conf))) if conf else ""
            self._set_text(row, 6, conf_text, color="#22C55E" if conf else None)

        self._update_count()

    def _set_text(self, row, col, text, color=None):
        item = QTableWidgetItem(text)
        item.setForeground(QColor(color or "#9CA3AF"))
        item.setToolTip(text)
        self.table.setItem(row, col, item)

    def _update_count(self):
        self.count_label.setText("%d application(s)" % len(self._apps))

    # ------------------------------------------------------------------ #
    def _apply_filter(self, *_args):
        query = self.search.text().strip().lower()
        include_hidden = self.show_all_check.isChecked()

        for row, app in enumerate(self._apps):
            hidden = not app.get("surfaceable", True) and not include_hidden
            matches = True
            if query:
                haystack = " ".join([
                    app.get("name") or "",
                    app.get("publisher") or "",
                    app.get("location") or "",
                    app.get("classification") or "",
                    " ".join(app.get("sources") or []),
                ]).lower()
                matches = query in haystack
            self.table.setRowHidden(row, hidden or not matches)

    # ------------------------------------------------------------------ #
    def _toggle_details(self, checked):
        self.details.setVisible(checked)
        if checked:
            self._update_details()

    def _update_details(self):
        if not self.details.isVisible():
            return
        app = self._selected_app()
        if app is None:
            self.details.setHtml("<span style='color:#6B7280'>Select a row.</span>")
            return
        self.details.setHtml(_details_html(app))

    def _selected_app(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return item.data(Qt.UserRole) if item else None

    # ------------------------------------------------------------------ #
    def _update_buttons(self):
        self.add_btn.setEnabled(bool(self.selected_paths()))

    def selected_paths(self):
        """Distinct launch paths of the selected, launchable rows."""
        paths = []
        for row in self.table.selectionModel().selectedRows():
            item = self.table.item(row.row(), 0)
            if item is None:
                continue
            app = item.data(Qt.UserRole) or {}
            path = app.get("path") or ""
            if path and app.get("launchable") and path not in paths:
                paths.append(path)
        return paths


# --------------------------------------------------------------------------- #
def _details_html(app) -> str:
    lines = []

    def block(title, value):
        lines.append(
            "<p><span style='color:#6B7280;'>%s</span><br/>"
            "<span style='color:#E5E7EB;'>%s</span></p>" % (title, value)
        )

    block("Application", app.get("name") or "(unknown)")
    block("Publisher", app.get("publisher") or "—")
    block("Version", app.get("version") or "—")
    block("Classification", app.get("classification") or "—")
    block("Install location", app.get("location") or "—")
    block("Installer type", (app.get("installer_type") or "—").upper())
    block("Architecture", app.get("architecture") or "—")
    conf = app.get("confidence")
    block("Confidence", ("%d%%" % int(round(conf))) if conf else "—")
    block("Uninstall command", app.get("uninstall_command") or "—")

    sources = ", ".join(app.get("sources") or []) or "—"
    block("Sources", sources)

    sig = app.get("signature") or {}
    if sig:
        signed = "Yes" if sig.get("is_signed") else "No"
        block("Signature", "%s (%s)" % (signed, sig.get("status") or "unknown"))
        if sig.get("subject"):
            block("Certificate subject", sig["subject"])

    components = app.get("components") or []
    if components:
        parts = []
        for comp in components:
            kind = comp.get("kind") or ""
            name = comp.get("name") or ""
            path = comp.get("path") or ""
            text = "<b>%s</b> %s" % (kind, name)
            if path:
                text += "<br/><span style='color:#6B7280;'>%s</span>" % path
            parts.append(text)
        block("Components", "<br/>".join(parts) if parts else "—")

    return ("<html><body style='font-family:Segoe UI;font-size:10pt;'>"
            + "".join(lines) + "</body></html>")
