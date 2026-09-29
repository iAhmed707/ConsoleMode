"""Dashboard page: overview of the current system state and quick actions."""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.pages.common import format_hdr, format_refresh, format_resolution


class DashboardPage(QWidget):
    """Summary of displays, audio, the active profile and running apps.

    The page polls every couple of seconds so it reflects changes made from any
    other page without manual intervention.
    """

    # The dashboard has no business launching or navigating itself; the main
    # window wires these to its own handlers.
    launch_requested = Signal()
    exit_requested = Signal()
    open_profiles_requested = Signal()

    def __init__(self, display_manager, audio_manager, profile_manager):
        super().__init__()
        self.display_manager = display_manager
        self.audio_manager = audio_manager
        self.profile_manager = profile_manager

        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        title = QLabel("Dashboard")
        title.setFont(QFont("Segoe UI", 22, QFont.Bold))
        layout.addWidget(title)

        layout.addLayout(self._build_actions())

        self.grid = QGridLayout()
        self.grid.setSpacing(16)

        self.console_card = self._create_card("Console Mode")
        self.console_content = QLabel("No profile is active.")
        self.console_content.setWordWrap(True)
        self.console_card.layout().addWidget(self.console_content)

        self.display_card = self._create_card("Displays")
        self.display_content = QLabel("No monitors detected.")
        self.display_content.setWordWrap(True)
        self.display_card.layout().addWidget(self.display_content)

        self.audio_card = self._create_card("Audio Output")
        self.audio_content = QLabel("No audio device.")
        self.audio_content.setWordWrap(True)
        self.audio_card.layout().addWidget(self.audio_content)

        self.apps_card = self._create_card("Applications")
        self.apps_content = QLabel("None configured.")
        self.apps_content.setWordWrap(True)
        self.apps_card.layout().addWidget(self.apps_content)

        self.grid.addWidget(self.console_card, 0, 0)
        self.grid.addWidget(self.display_card, 0, 1)
        self.grid.addWidget(self.audio_card, 1, 0)
        self.grid.addWidget(self.apps_card, 1, 1)
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, 1)

        layout.addLayout(self.grid)
        layout.addStretch()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(2000)

        self.refresh()

    # ---------- layout ----------
    def _build_actions(self):
        row = QHBoxLayout()
        row.setSpacing(10)

        self.launch_btn = QPushButton("Launch Profile")
        self.launch_btn.setObjectName("LaunchButton")
        self.launch_btn.clicked.connect(self.launch_requested.emit)
        row.addWidget(self.launch_btn)

        self.exit_btn = QPushButton("Exit Console Mode")
        self.exit_btn.clicked.connect(self.exit_requested.emit)
        row.addWidget(self.exit_btn)

        open_btn = QPushButton("Open Profiles")
        open_btn.clicked.connect(self.open_profiles_requested.emit)
        row.addWidget(open_btn)

        refresh_btn = QPushButton("Refresh Hardware")
        refresh_btn.clicked.connect(self.refresh_hardware)
        row.addWidget(refresh_btn)

        row.addStretch()
        return row

    def _create_card(self, title):
        card = QFrame()
        card.setObjectName("DetailPanel")
        card.setStyleSheet("""
            QFrame#DetailPanel {
                background: #1A1B1E;
                border-radius: 10px;
                padding: 16px;
            }
            QLabel {
                background: transparent;
            }
        """)
        layout = QVBoxLayout(card)
        label = QLabel(title)
        label.setFont(QFont("Segoe UI", 13, QFont.Bold))
        layout.addWidget(label)
        return card

    # ---------- refresh ----------
    def refresh_hardware(self):
        """Re-enumerate displays and audio, then redraw the cards."""
        self.display_manager.refresh()
        self.audio_manager.refresh()
        self.refresh()

    def refresh(self):
        self._refresh_console()
        self._refresh_displays()
        self._refresh_audio()
        self._refresh_apps()
        self._refresh_buttons()

    def _refresh_console(self):
        active = self.profile_manager.active_profile_name
        if active:
            running = self.profile_manager.running_apps()
            text = ("Console mode: <span style='color:#22C55E;'>Active</span>"
                    "<br>Profile: %s<br>Running apps: %d" % (active, running))
            self.console_content.setText(text)
        else:
            self.console_content.setText("Console mode: <span style='color:#9CA3AF;'>"
                                         "Inactive</span><br>No profile is running.")

    def _refresh_displays(self):
        monitors = self.display_manager.get_monitor_info()
        if not monitors:
            self.display_content.setText("No monitors detected.")
            return

        primary = next((m for m in monitors if m.get("is_primary")), monitors[0])
        hdr_text, _ = format_hdr(primary)
        lines = [
            "Primary: %s · %s @ %s" % (
                primary.get("label") or primary["name"],
                format_resolution(primary),
                format_refresh(primary),
            ),
            "HDR: %s" % hdr_text,
            "Connected: %d display(s)" % len(monitors),
        ]
        for mon in monitors:
            marker = " (Primary)" if mon.get("is_primary") else ""
            hdr = " · HDR" if mon.get("hdr_enabled") else ""
            lines.append("%s: %s @ %s%s%s" % (
                mon.get("label") or mon["name"],
                format_resolution(mon), format_refresh(mon), hdr, marker,
            ))
        self.display_content.setText("\n".join(lines))

    def _refresh_audio(self):
        if not self.audio_manager.is_available():
            self.audio_content.setText(self.audio_manager.unavailable_reason())
            return
        device = self.audio_manager.get_default_device()
        if device:
            self.audio_content.setText("Default: %s" % device.get("name", "Unknown"))
        else:
            self.audio_content.setText("No default audio device.")

    def _refresh_apps(self):
        configured = sum(len(p.get("apps", [])) for p in self.profile_manager.profiles)
        running = self.profile_manager.running_apps()
        lines = ["Configured: %d application(s)" % configured,
                 "Running: %d application(s)" % running]
        self.apps_content.setText("\n".join(lines))

    def _refresh_buttons(self):
        active = self.profile_manager.active_profile_name is not None
        self.exit_btn.setEnabled(active)
        self.launch_btn.setText("Exit Console Mode" if active else "Launch Profile")
        has_profiles = bool(self.profile_manager.profiles)
        self.launch_btn.setEnabled(has_profiles or active)
