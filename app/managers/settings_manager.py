"""Application settings: load/save settings.json and apply Windows behavior.

Settings are stored in ``settings.json`` beside the application and saved
atomically.  The two settings that change real OS state — autostart and the
profiles folder — are applied here so the Settings page never talks to Windows
directly.

Autostart uses the ``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run``
key, the standard per-user way to launch a program at logon.
"""

import json
import os
import sys
from pathlib import Path

from app.managers.paths import app_dir, default_profiles_dir

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "ConsoleMode"

# Hotkey actions with their default shortcuts. Kept here so both the Settings
# manager (persistence) and the Hotkeys page (editing) share one source of truth.
DEFAULT_HOTKEYS = {
    "toggle_console": "Ctrl+Alt+L",
    "exit_console": "Ctrl+Alt+X",
    "show_window": "Ctrl+Alt+G",
}

HOTKEY_LABELS = {
    "toggle_console": "Launch / exit console mode",
    "exit_console": "Exit console mode",
    "show_window": "Show ConsoleMode window",
}


def settings_file():
    return app_dir() / "settings.json"


class SettingsManager:
    """Reads and writes settings.json and applies the OS-level settings."""

    def __init__(self, path=None):
        self.path = Path(path) if path else settings_file()
        self.settings = self._load()

    # ---------- persistence ----------
    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def get(self, key, default=None):
        return self.settings.get(key, default)

    def set(self, key, value):
        """Update one setting and persist it. Returns ``(success, message)``."""
        self.settings[key] = value
        return self.save()

    def save(self):
        """Write settings.json atomically. Returns ``(success, message)``."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp_file = self.path.with_suffix(".json.tmp")
            with open(temp_file, "w", encoding="utf-8") as handle:
                json.dump(self.settings, handle, indent=2)
            os.replace(temp_file, self.path)
        except OSError as error:
            return False, "Could not save settings: %s" % error
        return True, "Settings saved."

    # ---------- profiles directory ----------
    def profiles_dir(self):
        """The configured profiles folder, or the default when unset."""
        value = self.settings.get("profiles_dir") or ""
        return str(value) if value.strip() else str(default_profiles_dir())

    def set_profiles_dir(self, path):
        return self.set("profiles_dir", str(path))

    # ---------- autostart ----------
    def autostart(self):
        return bool(self.settings.get("autostart", False))

    def set_autostart(self, enabled):
        """Store the flag and update the Windows Run key. Returns
        ``(success, message)``.
        """
        enabled = bool(enabled)
        self.settings["autostart"] = enabled
        saved, save_message = self.save()
        if not saved:
            return False, save_message

        if os.name != "nt":
            return True, "Autostart setting saved (only applies on Windows)."

        try:
            import winreg
        except ImportError:  # pragma: no cover - winreg is stdlib on Windows
            return True, "Autostart setting saved."

        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE,
            )
        except OSError as error:
            return False, "Could not open the Windows startup key: %s" % error

        try:
            if enabled:
                winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, self._start_command())
                return True, "ConsoleMode will now start with Windows."
            try:
                winreg.DeleteValue(key, RUN_VALUE)
            except FileNotFoundError:
                pass
            return True, "ConsoleMode will no longer start with Windows."
        except OSError as error:
            return False, "Could not update Windows startup: %s" % error
        finally:
            winreg.CloseKey(key)

    def _start_command(self):
        """The command Windows runs at logon.

        When frozen there is a single executable; in source form the Python
        interpreter is launched with the entry-point script.
        """
        if getattr(sys, "frozen", False):
            return '"%s"' % sys.executable
        script = Path(sys.argv[0]).resolve()
        return '"%s" "%s"' % (sys.executable, script)

    # ---------- hotkeys ----------
    def hotkeys(self):
        """Configured shortcuts for each action, falling back to defaults.

        An empty string is preserved on purpose: it means the user cleared
        the shortcut, and it must stay cleared across restarts instead of
        silently reverting to the default.
        """
        stored = self.settings.get("hotkeys") or {}
        if not isinstance(stored, dict):
            stored = {}
        result = dict(DEFAULT_HOTKEYS)
        for action, shortcut in stored.items():
            if action in result:
                result[action] = str(shortcut)
        return result

    def set_hotkey(self, action, shortcut):
        stored = dict(self.settings.get("hotkeys") or {})
        stored[action] = shortcut
        return self.set("hotkeys", stored)
