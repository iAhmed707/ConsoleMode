"""Settings page: profiles folder, Windows autostart, and language note.

Changes are saved and applied immediately — the profiles folder is re-pointed
through the ProfileManager and autostart writes the Windows Run key through the
SettingsManager, so the page never talks to Windows itself.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.managers.paths import default_profiles_dir


class SettingsPage(QWidget):
    """Application settings backed by SettingsManager and ProfileManager."""

    status = Signal(str)
    error = Signal(str)
    # Emitted after the profiles folder is switched so the main window can
    # reload every page that displays profile data.
    profiles_dir_changed = Signal()

    def __init__(self, settings_manager, profile_manager):
        super().__init__()
        self.settings = settings_manager
        self.profiles = profile_manager
        self._loading = True

        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        title = QLabel("Settings")
        title.setFont(QFont("Segoe UI", 22, QFont.Bold))
        layout.addWidget(title)

        layout.addWidget(self._section_label("Profiles Folder"))
        layout.addLayout(self._build_profiles_dir_row())

        layout.addWidget(self._section_label("Startup"))
        self.autostart_check = QCheckBox("Launch ConsoleMode when Windows starts")
        self.autostart_check.setChecked(self.settings.autostart())
        self.autostart_check.toggled.connect(self.on_autostart_toggled)
        layout.addWidget(self.autostart_check)

        layout.addWidget(self._section_label("Language"))
        language_note = QLabel("English — the interface is English-only for now.")
        language_note.setStyleSheet("color: #9CA3AF;")
        layout.addWidget(language_note)

        layout.addStretch()

        self._loading = False
        self.dir_edit.setText(self.settings.profiles_dir())

    def _build_profiles_dir_row(self):
        row = QHBoxLayout()
        self.dir_edit = QLineEdit()
        self.dir_edit.setReadOnly(True)
        self.dir_edit.setToolTip("Where profiles.json is stored")
        row.addWidget(self.dir_edit, 1)

        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self.browse_profiles_dir)
        row.addWidget(browse_btn)

        reset_btn = QPushButton("Reset to default")
        reset_btn.clicked.connect(self.reset_profiles_dir)
        row.addWidget(reset_btn)
        return row

    @staticmethod
    def _section_label(text):
        label = QLabel(text)
        label.setFont(QFont("Segoe UI", 11, QFont.Bold))
        return label

    # ---------- profiles folder ----------
    def browse_profiles_dir(self):
        chosen = QFileDialog.getExistingDirectory(
            self, "Select Profiles Folder", self.settings.profiles_dir()
        )
        if chosen:
            self._apply_profiles_dir(chosen)

    def reset_profiles_dir(self):
        self._apply_profiles_dir(str(default_profiles_dir()))

    def _apply_profiles_dir(self, path):
        if self.profiles.active_profile_name is not None:
            self.error.emit("Exit console mode before changing the profiles folder.")
            QMessageBox.warning(
                self, "Console mode is active",
                "Exit console mode before changing the profiles folder.",
            )
            return

        ok, message = self.profiles.set_profiles_dir(path)
        if not ok:
            self.error.emit(message)
            QMessageBox.warning(self, "Could not change profiles folder", message)
            return

        self.settings.set_profiles_dir(self.profiles.profiles_dir)
        self.dir_edit.setText(str(self.profiles.profiles_dir))
        self.status.emit(message)
        self.profiles_dir_changed.emit()

    # ---------- autostart ----------
    def on_autostart_toggled(self, checked):
        if self._loading:
            return
        ok, message = self.settings.set_autostart(checked)
        if ok:
            self.status.emit(message)
        else:
            self.error.emit(message)
            # Revert the checkbox so it reflects reality, not the click.
            self._loading = True
            self.autostart_check.setChecked(self.settings.autostart())
            self._loading = False
            QMessageBox.warning(self, "Could not change autostart", message)
