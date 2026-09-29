"""ConsoleMode - turn a gaming PC into a console with one button.

This module owns the main window, the theme and the navigation. The actual
work lives in app/managers, and each section of the UI in app/pages.
"""

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.managers.audio_manager import AudioManager
from app.managers.controller_manager import ControllerManager
from app.managers.display_manager import DisplayManager
from app.managers.hotkey_manager import HotkeyManager
from app.managers.log_manager import LogManager
from app.managers.profile_manager import ProfileManager
from app.managers.settings_manager import SettingsManager
from app.pages import (
    ApplicationsPage,
    AudioPage,
    ControllerPage,
    DashboardPage,
    GraphicalDisplaysPage,
    HotkeysPage,
    LogsPage,
    ProfilesPage,
    SettingsPage,
)

STYLESHEET = """
QMainWindow{
    background:#202124;
}
QWidget{
    background:#202124;
    color:white;
    font-family:Segoe UI;
    font-size:11pt;
}
QFrame#Sidebar{
    background:#18191c;
}
QFrame#DetailPanel{
    background:#1A1B1E;
    border-radius:10px;
}
/* Labels and checkboxes would otherwise paint the window colour over the
   panel they sit on. */
QLabel, QCheckBox{
    background:transparent;
}
QListWidget{
    background:#1E1E1E;
    border:none;
    border-radius:8px;
    outline:none;
}
QListWidget::item{
    padding:6px 10px;
    margin:2px;
    border-radius:6px;
}
QListWidget::item:selected{
    background:#3B82F6;
}
/* The navigation list is roomier than the in-page lists. */
QFrame#Sidebar QListWidget{
    background:transparent;
}
QFrame#Sidebar QListWidget::item{
    padding:12px;
    margin:4px;
    border-radius:8px;
}
QPushButton{
    background:#3B82F6;
    border:none;
    border-radius:8px;
    padding:10px;
}
QPushButton:hover{
    background:#2563EB;
}
QPushButton:disabled{
    background:#374151;
    color:#9CA3AF;
}
QPushButton#LaunchButton{
    background:#16A34A;
    font-weight:bold;
    padding:12px;
}
QPushButton#LaunchButton:hover{
    background:#15803D;
}
QLineEdit{
    background:#2C2C2C;
    border:1px solid #3F3F46;
    border-radius:6px;
    padding:8px;
}
QTableWidget{
    background:#1E1E1E;
    alternate-background-color:#242528;
    border:none;
    border-radius:8px;
    gridline-color:#2F3033;
    /* Deeper than the sidebar's blue so the colour-coded HDR and
       Role text stays readable on the selected row. */
    selection-background-color:#1E3A8A;
}
QTableWidget::item{
    padding:6px 10px;
}
QHeaderView::section{
    background:#18191c;
    color:#9CA3AF;
    border:none;
    border-bottom:1px solid #2F3033;
    padding:8px 10px;
    font-weight:bold;
}
QComboBox{
    background:#2C2C2C;
    border:1px solid #3F3F46;
    border-radius:6px;
    padding:6px 10px;
}
QComboBox QAbstractItemView{
    background:#1E1E1E;
    selection-background-color:#3B82F6;
    border:1px solid #3F3F46;
}
QKeySequenceEdit{
    background:#2C2C2C;
    border:1px solid #3F3F46;
    border-radius:6px;
    padding:8px;
}
QStatusBar{
    background:#18191c;
    color:#9CA3AF;
}
"""

# Sidebar entries, in stack order.
PAGE_NAMES = [
    "Dashboard",
    "Profiles",
    "Displays",
    "Audio",
    "Applications",
    "Controller",
    "Hotkeys",
    "Settings",
    "Logs",
]

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("ConsoleMode")
        self.resize(1400, 850)
        self.setStyleSheet(STYLESHEET)

        # ---------- managers ----------
        self.settings_manager = SettingsManager()
        self.log_manager = LogManager()

        self.display_manager = DisplayManager()
        self.display_manager.refresh()
        self.audio_manager = AudioManager()
        self.profile_manager = ProfileManager(self.settings_manager.profiles_dir())
        self.controller_manager = ControllerManager()
        self.hotkey_manager = HotkeyManager()

        # ---------- global hotkeys ----------
        app = QApplication.instance()
        if app is not None and self.hotkey_manager.is_available():
            app.installNativeEventFilter(self.hotkey_manager)
        self._register_hotkeys()

        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)

        # ---------- sidebar ----------
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(240)
        sidebar_layout = QVBoxLayout(sidebar)

        logo = QLabel("🎮 ConsoleMode")
        logo.setFont(QFont("Segoe UI", 18, QFont.Bold))
        logo.setAlignment(Qt.AlignCenter)
        sidebar_layout.addWidget(logo)

        self.menu = QListWidget()
        for name in PAGE_NAMES:
            self.menu.addItem(QListWidgetItem(name))
        sidebar_layout.addWidget(self.menu)

        self.launch_btn = QPushButton("Launch Profile")
        self.launch_btn.setObjectName("LaunchButton")
        self.launch_btn.clicked.connect(self.launch_active_profile)
        sidebar_layout.addWidget(self.launch_btn)

        # ---------- pages ----------
        self.dashboard_page = DashboardPage(
            self.display_manager, self.audio_manager, self.profile_manager
        )
        self.profiles_page = ProfilesPage(
            self.profile_manager, self.display_manager, self.audio_manager
        )
        self.displays_page = GraphicalDisplaysPage(self.display_manager)
        self.audio_page = AudioPage(self.audio_manager)
        self.applications_page = ApplicationsPage(self.profile_manager)
        self.controller_page = ControllerPage(self.controller_manager)
        self.hotkeys_page = HotkeysPage(self.hotkey_manager, self.settings_manager)
        self.settings_page = SettingsPage(self.settings_manager, self.profile_manager)
        self.logs_page = LogsPage(self.log_manager)

        self.stack = QStackedWidget()
        for page in (
            self.dashboard_page,
            self.profiles_page,
            self.displays_page,
            self.audio_page,
            self.applications_page,
            self.controller_page,
            self.hotkeys_page,
            self.settings_page,
            self.logs_page,
        ):
            self.stack.addWidget(page)

        self.menu.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.menu.setCurrentRow(0)

        layout.addWidget(sidebar)
        layout.addWidget(self.stack)

        # ---------- status bar & logging ----------
        self.statusBar().showMessage("Ready.")
        for page in (
            self.profiles_page,
            self.displays_page,
            self.audio_page,
            self.applications_page,
            self.settings_page,
            self.dashboard_page,
            self.controller_page,
            self.hotkeys_page,
        ):
            if hasattr(page, "status"):
                page.status.connect(self.on_status)
            if hasattr(page, "error"):
                page.error.connect(self.on_error)

        # ---------- cross-page synchronization ----------
        self.profiles_page.console_mode_changed.connect(self.on_console_mode_changed)
        self.profiles_page.profiles_changed.connect(self.on_profiles_changed)
        self.settings_page.profiles_dir_changed.connect(self.on_profiles_dir_changed)

        self.dashboard_page.launch_requested.connect(self.launch_active_profile)
        self.dashboard_page.exit_requested.connect(self.profiles_page.exit_console_mode)
        self.dashboard_page.open_profiles_requested.connect(
            lambda: self.menu.setCurrentRow(PAGE_NAMES.index("Profiles"))
        )

        self.hotkey_manager.signals.toggle_console.connect(self.launch_active_profile)
        self.hotkey_manager.signals.exit_console.connect(self.profiles_page.exit_console_mode)
        self.hotkey_manager.signals.show_window.connect(self.show_window)

        # Log every press so the Logs page shows hotkeys are being received.
        self.hotkey_manager.signals.toggle_console.connect(
            lambda: self.log_manager.info("Hotkey pressed: launch / exit console mode."))
        self.hotkey_manager.signals.exit_console.connect(
            lambda: self.log_manager.info("Hotkey pressed: exit console mode."))
        self.hotkey_manager.signals.show_window.connect(
            lambda: self.log_manager.info("Hotkey pressed: show ConsoleMode window."))

        self.update_launch_button()
        self.log_manager.info("ConsoleMode started.")

    # ---------- status / logging ----------
    def on_status(self, message):
        self.statusBar().showMessage(message, 10000)
        self.log_manager.info(message)

    def on_error(self, message):
        self.statusBar().showMessage("Error: %s" % message, 10000)
        self.log_manager.error(message)

    # ---------- hotkeys ----------
    def _register_hotkeys(self):
        """Register configured shortcuts; a busy one is reported, not fatal."""
        for action, shortcut in self.settings_manager.hotkeys().items():
            ok, message = self.hotkey_manager.register_hotkey(action, shortcut)
            if not ok:
                self.log_manager.error(message)
            else:
                self.log_manager.info(message)

    def show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # ---------- launch button ----------
    def launch_active_profile(self):
        """The one-button entry point: launch, or exit if already in console mode."""
        if self.profile_manager.active_profile_name is not None:
            self.profiles_page.exit_console_mode()
            return

        profile = self.profiles_page.current_profile()
        if profile is None:
            self.on_status("Create a profile first.")
            self.menu.setCurrentRow(PAGE_NAMES.index("Profiles"))
            return

        self.profiles_page.launch_profile(profile["name"])

    def on_console_mode_changed(self, active):
        self.update_launch_button()
        self.dashboard_page.refresh()

    def on_profiles_changed(self):
        """Profiles were created/renamed/deleted; refresh dependent views."""
        self.update_launch_button()
        self.applications_page.populate_apps()
        self.dashboard_page.refresh()

    def on_profiles_dir_changed(self):
        """The profiles folder moved; re-read profiles everywhere."""
        self.profiles_page.reload_profiles()
        self.applications_page.populate_apps()
        self.dashboard_page.refresh()
        self.update_launch_button()

    def update_launch_button(self):
        """The sidebar button doubles as the exit while a profile is active."""
        active_name = self.profile_manager.active_profile_name
        if active_name:
            self.launch_btn.setText("Exit Console Mode")
            self.launch_btn.setEnabled(True)
        else:
            self.launch_btn.setText("Launch Profile")
            self.launch_btn.setEnabled(bool(self.profile_manager.profiles))

    # ---------- shutdown ----------
    def closeEvent(self, event):
        """Warn before quitting while a profile's apps are still running."""
        if self.profile_manager.running_apps():
            from PySide6.QtWidgets import QMessageBox

            answer = QMessageBox.question(
                self, "Console mode is active",
                "'%s' is still running. Exit console mode and restore your "
                "previous settings before quitting?"
                % self.profile_manager.active_profile_name,
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                QMessageBox.Yes,
            )
            if answer == QMessageBox.Cancel:
                event.ignore()
                return
            if answer == QMessageBox.Yes:
                self.profile_manager.exit_console_mode(
                    self.display_manager, self.audio_manager
                )

        self.hotkey_manager.unregister_all()
        self.log_manager.info("ConsoleMode closed.")
        super().closeEvent(event)

# ---------- Run ----------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    app.aboutToQuit.connect(window.hotkey_manager.unregister_all)
    sys.exit(app.exec())
