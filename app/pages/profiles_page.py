"""Profiles page: create, edit and launch console-mode profiles.

Edits are written straight into the profile and saved, so there is no "unsaved
changes" state to lose - switching profiles in the list can never discard work.
"""

import threading
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.managers.installed_apps import InstalledAppsManager
from app.pages.common import describe_display_config
from app.pages.installed_apps_dialog import InstalledAppsDialog


class _DiscoveryWorker(QThread):
    """Runs the (parallel) discovery off the UI thread and streams progress."""

    progress = Signal(str)
    finished_apps = Signal(list)
    failed = Signal(str)

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self._manager = manager
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def run(self):
        try:
            apps = self._manager.refresh(
                on_log=self.progress.emit, cancel_event=self._cancel,
            )
            self.finished_apps.emit(apps)
        except Exception as error:  # noqa: BLE001 - report, never crash the UI
            self.failed.emit(str(error))

class ProfilesPage(QWidget):
    """Master/detail editor over ProfileManager."""

    # Emitted with a one-line result for the main window's status bar.
    status = Signal(str)
    # Emitted when an operation fails, so the main window can log it as an error.
    error = Signal(str)
    # Emitted when a profile is launched or console mode is exited.
    console_mode_changed = Signal(bool)
    # Emitted after create/duplicate/rename/delete so dependent pages refresh.
    profiles_changed = Signal()

    def __init__(self, profile_manager, display_manager, audio_manager):
        super().__init__()
        self.profiles = profile_manager
        self.displays = display_manager
        self.audio = audio_manager
        self.installed_apps = None  # created lazily when the picker opens

        # Set while the form is being filled from a profile, so the change
        # handlers do not write the old profile's values back.
        self._loading = False

        root = QVBoxLayout(self)
        root.setSpacing(14)

        title = QLabel("Profiles")
        title.setFont(QFont("Segoe UI", 22, QFont.Bold))
        root.addWidget(title)

        subtitle = QLabel(
            "A profile stores a display layout, an audio device and the apps to "
            "launch. Changes are saved as you make them."
        )
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        body = QHBoxLayout()
        body.setSpacing(16)
        body.addLayout(self._build_list_panel(), 0)
        body.addWidget(self._build_detail_panel(), 1)
        root.addLayout(body, 1)

        self.reload_profiles()

    # ---------- left panel ----------
    def _build_list_panel(self):
        column = QVBoxLayout()
        column.setSpacing(8)

        self.profile_list = QListWidget()
        self.profile_list.setFixedWidth(260)
        self.profile_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.profile_list.currentItemChanged.connect(self.on_profile_selected)
        column.addWidget(self.profile_list, 1)

        buttons = QHBoxLayout()
        new_btn = QPushButton("New")
        new_btn.clicked.connect(self.create_profile)
        buttons.addWidget(new_btn)

        duplicate_btn = QPushButton("Duplicate")
        duplicate_btn.clicked.connect(self.duplicate_profile)
        buttons.addWidget(duplicate_btn)

        delete_btn = QPushButton("Delete")
        delete_btn.clicked.connect(self.delete_profile)
        buttons.addWidget(delete_btn)
        column.addLayout(buttons)

        return column

    # ---------- right panel ----------
    def _build_detail_panel(self):
        panel = QFrame()
        panel.setObjectName("DetailPanel")
        layout = QVBoxLayout(panel)
        layout.setSpacing(12)

        # Name
        layout.addWidget(self._section_label("Profile name"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("TV Mode")
        # editingFinished, not textChanged: renaming on every keystroke would
        # fight the uniqueness check.
        self.name_edit.editingFinished.connect(self.rename_profile)
        layout.addWidget(self.name_edit)

        # Displays
        layout.addWidget(self._section_label("Displays"))
        self.display_summary = QLabel("No display settings saved.")
        self.display_summary.setWordWrap(True)
        self.display_summary.setStyleSheet("color:#9CA3AF;")
        layout.addWidget(self.display_summary)

        capture_btn = QPushButton("Capture current display layout")
        capture_btn.clicked.connect(self.capture_displays)
        layout.addWidget(capture_btn)

        # Audio
        layout.addWidget(self._section_label("Audio output"))
        self.audio_combo = QComboBox()
        self.audio_combo.currentIndexChanged.connect(self.on_audio_changed)
        layout.addWidget(self.audio_combo)

        # Applications
        layout.addWidget(self._section_label("Applications"))
        self.apps_list = QListWidget()
        self.apps_list.setMinimumHeight(120)
        layout.addWidget(self.apps_list, 1)

        app_buttons = QHBoxLayout()
        add_app_btn = QPushButton("Add application…")
        add_app_btn.clicked.connect(self.add_app)
        app_buttons.addWidget(add_app_btn)

        add_installed_btn = QPushButton("Add installed app…")
        add_installed_btn.clicked.connect(self.add_installed_app)
        app_buttons.addWidget(add_installed_btn)

        remove_app_btn = QPushButton("Remove")
        remove_app_btn.clicked.connect(self.remove_app)
        app_buttons.addWidget(remove_app_btn)
        app_buttons.addStretch()
        layout.addLayout(app_buttons)

        self.close_apps_check = QCheckBox("Close these applications when exiting console mode")
        self.close_apps_check.toggled.connect(self.on_close_apps_toggled)
        layout.addWidget(self.close_apps_check)

        self.move_apps_check = QCheckBox("Move launched applications to the primary display")
        self.move_apps_check.toggled.connect(self.on_move_apps_toggled)
        layout.addWidget(self.move_apps_check)

        # Launch / exit
        actions = QHBoxLayout()
        self.launch_btn = QPushButton("Launch this profile")
        self.launch_btn.setObjectName("LaunchButton")
        self.launch_btn.clicked.connect(self.launch_selected)
        actions.addWidget(self.launch_btn)

        self.exit_btn = QPushButton("Exit console mode")
        self.exit_btn.clicked.connect(self.exit_console_mode)
        actions.addWidget(self.exit_btn)
        actions.addStretch()
        layout.addLayout(actions)

        return panel

    @staticmethod
    def _section_label(text):
        label = QLabel(text)
        label.setFont(QFont("Segoe UI", 11, QFont.Bold))
        return label

    # ---------- loading ----------
    def reload_profiles(self, select_name=None):
        """Rebuild the profile list, keeping (or forcing) a selection."""
        self._loading = True
        self.profile_list.clear()
        for profile in self.profiles.profiles:
            item = QListWidgetItem(profile["name"])
            item.setData(Qt.UserRole, profile["name"])
            self.profile_list.addItem(item)
        self._loading = False

        if self.profile_list.count() == 0:
            self.load_profile(None)
            return

        row = 0
        if select_name:
            for index in range(self.profile_list.count()):
                if self.profile_list.item(index).data(Qt.UserRole) == select_name:
                    row = index
                    break
        self.profile_list.setCurrentRow(row)

    def current_profile(self):
        """The profile dict behind the list selection, or None."""
        item = self.profile_list.currentItem()
        if item is None:
            return None
        return self.profiles.get(item.data(Qt.UserRole))

    def on_profile_selected(self, current, previous):
        if self._loading:
            return
        self.load_profile(self.current_profile())

    def load_profile(self, profile):
        """Fill the form from a profile (or clear it when there is none)."""
        self._loading = True
        try:
            has_profile = profile is not None
            for widget in (self.name_edit, self.audio_combo, self.apps_list,
                           self.close_apps_check, self.move_apps_check, self.launch_btn):
                widget.setEnabled(has_profile)

            if not has_profile:
                self.name_edit.clear()
                self.audio_combo.clear()
                self.apps_list.clear()
                self.display_summary.setText("No profile selected.")
                self.close_apps_check.setChecked(False)
                self.move_apps_check.setChecked(False)
                return

            self.name_edit.setText(profile["name"])
            self.display_summary.setText(describe_display_config(profile["display"]))
            self.close_apps_check.setChecked(profile.get("close_apps_on_exit", True))
            self.move_apps_check.setChecked(profile.get("move_apps_to_primary", True))
            self._populate_audio(profile)
            self._populate_apps(profile)
        finally:
            self._loading = False

        self.update_console_buttons()

    def _populate_audio(self, profile):
        self.audio_combo.clear()

        if not self.audio.is_available():
            self.audio_combo.addItem("Audio switching unavailable", None)
            self.audio_combo.setEnabled(False)
            return

        self.audio_combo.setEnabled(True)
        self.audio_combo.addItem("Do not change audio", None)

        saved = profile.get("audio") or {}
        devices = self.audio.get_devices()
        for device in devices:
            self.audio_combo.addItem(device["name"], device)
            if device["id"] == saved.get("id") or device["name"] == saved.get("name"):
                self.audio_combo.setCurrentIndex(self.audio_combo.count() - 1)

        # A saved device that is not currently connected must not silently
        # become "do not change" - show it so the profile keeps its intent.
        if saved.get("name") and self.audio_combo.currentIndex() == 0:
            self.audio_combo.addItem("%s (not connected)" % saved["name"], dict(saved))
            self.audio_combo.setCurrentIndex(self.audio_combo.count() - 1)

    def _populate_apps(self, profile):
        self.apps_list.clear()
        for app_path in profile.get("apps", []):
            item = QListWidgetItem(Path(app_path).name)
            item.setToolTip(app_path)
            item.setData(Qt.UserRole, app_path)
            if not Path(app_path).exists():
                item.setText("%s  (missing)" % Path(app_path).name)
                item.setForeground(Qt.red)
            self.apps_list.addItem(item)

    # ---------- profile CRUD ----------
    def create_profile(self):
        """Create a profile seeded with the current display and audio state."""
        profile = self.profiles.create("New Profile", self.displays, self.audio)
        self.reload_profiles(profile["name"])
        self.profiles_changed.emit()
        self.status.emit("Created profile '%s' from the current setup." % profile["name"])

    def duplicate_profile(self):
        profile = self.current_profile()
        if profile is None:
            return
        copy = self.profiles.duplicate(profile["name"])
        if copy is None:
            return
        self.reload_profiles(copy["name"])
        self.profiles_changed.emit()
        self.status.emit("Duplicated to '%s'." % copy["name"])

    def delete_profile(self):
        profile = self.current_profile()
        if profile is None:
            return

        answer = QMessageBox.question(
            self, "Delete profile",
            "Delete '%s'? This cannot be undone." % profile["name"],
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        name = profile["name"]
        ok, message = self.profiles.delete(name)
        self.reload_profiles()
        self.profiles_changed.emit()
        if ok:
            self.status.emit("Deleted '%s'." % name)
        else:
            self.error.emit(message)

    def rename_profile(self):
        if self._loading:
            return
        profile = self.current_profile()
        if profile is None:
            return

        new_name = self.name_edit.text().strip()
        if not new_name or new_name == profile["name"]:
            return

        old_name = profile["name"]
        ok, message = self.profiles.rename(old_name, new_name)
        if not ok:
            self.error.emit(message)
            QMessageBox.warning(self, "Could not rename", message)
            self.name_edit.setText(old_name)
            return

        self.reload_profiles(new_name)
        self.profiles_changed.emit()
        self.status.emit("Renamed '%s' to '%s'." % (old_name, new_name))

    # ---------- field edits ----------
    def capture_displays(self):
        """Store the current monitor layout (and HDR state) in the profile."""
        profile = self.current_profile()
        if profile is None:
            return

        profile["display"] = self.displays.capture_layout()
        self.profiles.save()
        self.display_summary.setText(describe_display_config(profile["display"]))
        self.status.emit("Saved the current display layout to '%s'." % profile["name"])

    def on_audio_changed(self, index):
        if self._loading:
            return
        profile = self.current_profile()
        if profile is None:
            return

        device = self.audio_combo.currentData()
        profile["audio"] = ({"id": device.get("id"), "name": device.get("name")}
                            if device else {"id": None, "name": None})
        self.profiles.save()

    def on_close_apps_toggled(self, checked):
        if self._loading:
            return
        profile = self.current_profile()
        if profile is None:
            return
        profile["close_apps_on_exit"] = checked
        self.profiles.save()

    def on_move_apps_toggled(self, checked):
        if self._loading:
            return
        profile = self.current_profile()
        if profile is None:
            return
        profile["move_apps_to_primary"] = checked
        self.profiles.save()

    def add_app(self):
        profile = self.current_profile()
        if profile is None:
            return

        paths, _ = QFileDialog.getOpenFileNames(
            self, "Choose applications to launch", "",
            "Applications (*.exe *.lnk *.bat *.cmd);;All files (*)",
        )
        if not paths:
            return

        for path in paths:
            if path not in profile["apps"]:
                profile["apps"].append(path)
        self.profiles.save()
        self._loading = True
        self._populate_apps(profile)
        self._loading = False
        self.status.emit("Added %d application(s) to '%s'." % (len(paths), profile["name"]))

    def add_installed_app(self):
        """Pick from Windows-installed applications and add them to the profile.

        Discovery runs on a background thread so the UI stays responsive; a
        progress dialog streams per-scanner log lines and offers cancellation.
        """
        profile = self.current_profile()
        if profile is None:
            return

        if self.installed_apps is None:
            self.installed_apps = InstalledAppsManager()

        self._discovery_progress = QProgressDialog(
            "Starting scan…", "Cancel", 0, 0, self,
        )
        self._discovery_progress.setWindowTitle("Discover installed apps")
        self._discovery_progress.setWindowModality(Qt.WindowModal)
        self._discovery_progress.setMinimumDuration(0)
        self._discovery_progress.setAutoClose(False)

        self._discovery_worker = _DiscoveryWorker(self.installed_apps, self)
        self._discovery_worker.progress.connect(self._on_discovery_progress)
        self._discovery_worker.finished_apps.connect(self._on_discovery_finished)
        self._discovery_worker.failed.connect(self._on_discovery_failed)
        self._discovery_progress.canceled.connect(self._discovery_worker.cancel)
        self._discovery_worker.finished.connect(self._discovery_progress.close)
        self._discovery_worker.finished.connect(self._discovery_worker.deleteLater)
        self._discovery_worker.start()

    def _on_discovery_progress(self, message):
        if self._discovery_progress is not None:
            self._discovery_progress.setLabelText(message)
        self.status.emit(message)

    def _on_discovery_failed(self, message):
        self.error.emit("Installed-app discovery failed: %s" % message)
        QMessageBox.warning(self, "Discovery failed",
                            "Could not discover installed applications:\n\n%s" % message)

    def _on_discovery_finished(self, apps):
        profile = self.current_profile()
        if profile is None:
            return

        launchable = [a for a in apps if a.get("launchable")]
        if not launchable:
            QMessageBox.information(
                self, "No installed applications",
                "No launchable installed applications were found.",
            )
            return

        dialog = InstalledAppsDialog(apps, self)
        if dialog.exec() != QDialog.Accepted:
            return

        paths = dialog.selected_paths()
        added = [p for p in paths if p not in profile["apps"]]
        if not added:
            self.status.emit("Those applications are already in '%s'." % profile["name"])
            return

        profile["apps"].extend(added)
        self.profiles.save()
        self._loading = True
        self._populate_apps(profile)
        self._loading = False
        self.status.emit("Added %d installed application(s) to '%s'."
                         % (len(added), profile["name"]))

    def remove_app(self):
        profile = self.current_profile()
        item = self.apps_list.currentItem()
        if profile is None or item is None:
            return

        path = item.data(Qt.UserRole)
        if path in profile["apps"]:
            profile["apps"].remove(path)
            self.profiles.save()
        self._loading = True
        self._populate_apps(profile)
        self._loading = False

    # ---------- console mode ----------
    def launch_selected(self):
        """Launch the selected profile."""
        profile = self.current_profile()
        if profile is None:
            return
        self.launch_profile(profile["name"])

    def launch_profile(self, name):
        """Apply a profile's displays and audio, then start its apps."""
        previous = self.displays.capture_layout()
        success, messages = self.profiles.launch(name, self.displays, self.audio)

        self.update_console_buttons()
        self.console_mode_changed.emit(True)
        self.status.emit("Launched '%s'." % name if success else
                         "Launched '%s' with problems." % name)

        if not success:
            self.error.emit("Launched '%s' with problems: %s" % (name, "; ".join(messages)))
            QMessageBox.warning(
                self, "Profile launched with problems",
                "Some steps did not complete:\n\n• %s" % "\n• ".join(messages),
            )
        # Keep the pre-launch layout available for the log, even on success.
        self._previous_layout = previous

    def exit_console_mode(self):
        """Close the profile's apps and restore the previous display/audio state."""
        if self.profiles.active_profile_name is None:
            self.status.emit("No profile is currently active.")
            return

        name = self.profiles.active_profile_name
        success, messages = self.profiles.exit_console_mode(self.displays, self.audio)

        self.update_console_buttons()
        self.console_mode_changed.emit(False)
        self.status.emit("Exited console mode ('%s')." % name)

        if not success:
            self.error.emit("Exited '%s' with problems: %s" % (name, "; ".join(messages)))
            QMessageBox.warning(
                self, "Exited with problems",
                "Some steps did not complete:\n\n• %s" % "\n• ".join(messages),
            )

    def update_console_buttons(self):
        """Only offer Exit while a profile is actually active."""
        active = self.profiles.active_profile_name is not None
        self.exit_btn.setEnabled(active)
