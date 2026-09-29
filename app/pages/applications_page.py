"""Applications page: list all apps from all profiles and launch them directly."""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

class ApplicationsPage(QWidget):
    """Shows all applications from all profiles with launch and add-to-profile actions."""

    status = Signal(str)
    error = Signal(str)

    COLUMNS = ["Application", "Path", "Used In Profiles", "Actions"]

    def __init__(self, profile_manager):
        super().__init__()
        self.profile_manager = profile_manager

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        title = QLabel("Applications")
        title.setFont(QFont("Segoe UI", 22, QFont.Bold))
        layout.addWidget(title)

        subtitle = QLabel(
            "All applications stored across profiles. You can launch any app directly "
            "or add it to a profile."
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideRight)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        layout.addWidget(self.table, 1)

        # Controls
        controls = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.populate_apps)
        controls.addWidget(self.refresh_btn)

        controls.addStretch()
        layout.addLayout(controls)

        self.populate_apps()

    def populate_apps(self):
        """Collect all apps from all profiles and display them."""
        self.table.setRowCount(0)
        app_map = {}  # path -> list of profile names

        for profile in self.profile_manager.profiles:
            profile_name = profile.get("name", "Unnamed")
            for app_path in profile.get("apps", []):
                if app_path not in app_map:
                    app_map[app_path] = []
                app_map[app_path].append(profile_name)

        if not app_map:
            self.table.setRowCount(1)
            item = QTableWidgetItem("No applications found. Add some in Profiles > Applications.")
            item.setForeground(QColor("#9CA3AF"))
            self.table.setItem(0, 0, item)
            self.table.setSpan(0, 0, 1, len(self.COLUMNS))
            return

        self.table.setRowCount(len(app_map))

        for row, (app_path, profiles) in enumerate(app_map.items()):
            name = Path(app_path).name if app_path else "Unknown"
            name_item = QTableWidgetItem(name)
            if not Path(app_path).exists():
                name_item.setForeground(QColor("#EF4444"))
            self.table.setItem(row, 0, name_item)

            path_item = QTableWidgetItem(app_path)
            path_item.setToolTip(app_path)
            path_item.setForeground(QColor("#9CA3AF"))
            self.table.setItem(row, 1, path_item)

            profiles_text = ", ".join(profiles) if profiles else "None"
            profile_item = QTableWidgetItem(profiles_text)
            if profiles:
                profile_item.setForeground(QColor("#93C5FD"))
            self.table.setItem(row, 2, profile_item)

            # Actions column: Launch button + Add to profile combo
            widget = QWidget()
            action_layout = QHBoxLayout(widget)
            action_layout.setContentsMargins(0, 0, 0, 0)
            action_layout.setSpacing(6)

            launch_btn = QPushButton("Launch")
            launch_btn.setFixedWidth(60)
            launch_btn.clicked.connect(
                lambda checked, path=app_path: self.launch_app(path)
            )
            action_layout.addWidget(launch_btn)

            profile_combo = QComboBox()
            profile_combo.addItem("Add to...", None)
            for profile in self.profile_manager.profiles:
                pname = profile.get("name", "Unnamed")
                profile_combo.addItem(pname, pname)
                if app_path in profile.get("apps", []):
                    profile_combo.setItemData(profile_combo.count() - 1, QColor("#22C55E"), Qt.ForegroundRole)
            profile_combo.currentIndexChanged.connect(
                lambda idx, path=app_path, combo=profile_combo: self.add_app_to_profile(path, combo)
            )
            action_layout.addWidget(profile_combo)

            self.table.setCellWidget(row, 3, widget)

        self.table.resizeRowsToContents()
        self._fit_table_height()

    def _fit_table_height(self):
        """Auto-size table height to fit rows."""
        self.table.resizeRowsToContents()
        height = self.table.horizontalHeader().height()
        for row in range(self.table.rowCount()):
            height += self.table.rowHeight(row)
        height += 2 * self.table.frameWidth()
        height += self.table.horizontalScrollBar().sizeHint().height()
        if self.table.maximumHeight() != height:
            self.table.setFixedHeight(height)

    def launch_app(self, app_path):
        """Launch a single application directly."""
        path = Path(app_path)
        if not path.exists():
            QMessageBox.warning(self, "Application not found", f"Cannot find: {app_path}")
            self.error.emit(f"Application not found: {app_path}")
            return

        try:
            import subprocess
            subprocess.Popen([str(path)], cwd=str(path.parent))
            self.status.emit(f"Launched: {path.name}")
        except Exception as e:
            QMessageBox.warning(self, "Launch error", str(e))
            self.error.emit(f"Failed to launch: {path.name}: {e}")

    def add_app_to_profile(self, app_path, combo):
        """Add an application to the selected profile."""
        profile_name = combo.currentData()
        if not profile_name:
            return

        profile = self.profile_manager.get(profile_name)
        if not profile:
            self.status.emit(f"Profile '{profile_name}' no longer exists.")
            return

        if app_path in profile.get("apps", []):
            self.status.emit(f"'{Path(app_path).name}' already in '{profile_name}'.")
            combo.setCurrentIndex(0)  # reset to "Add to..."
            return

        profile.setdefault("apps", []).append(app_path)
        self.profile_manager.save()
        self.status.emit(f"Added '{Path(app_path).name}' to '{profile_name}'.")
        self.populate_apps()  # Refresh the table
