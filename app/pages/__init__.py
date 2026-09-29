"""UI pages shown in the main window's stacked widget."""

from .applications_page import ApplicationsPage
from .audio_page import AudioPage
from .common import PlaceholderPage
from .controller_page import ControllerPage
from .dashboard_page import DashboardPage
from .displays_page import GraphicalDisplaysPage
from .hotkeys_page import HotkeysPage
from .logs_page import LogsPage
from .profiles_page import ProfilesPage
from .settings_page import SettingsPage

__all__ = [
    "ApplicationsPage",
    "AudioPage",
    "ControllerPage",
    "DashboardPage",
    "GraphicalDisplaysPage",
    "HotkeysPage",
    "LogsPage",
    "PlaceholderPage",
    "ProfilesPage",
    "SettingsPage",
]
