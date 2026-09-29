"""Application-wide logging.

Every page and manager reports through this one object, so the Logs page shows
a single, timestamped, ordered stream and errors are distinguishable from
normal status messages.  Entries are also appended to a plain-text file so
problems can be diagnosed after the fact; file writing never raises.
"""

from datetime import datetime

from PySide6.QtCore import QObject, Signal

from app.managers.paths import app_dir


class LogManager(QObject):
    """Collects timestamped log entries and broadcasts them to the UI.

    ``entry_added(timestamp, message, is_error)`` is emitted for every entry;
    the Logs page connects to it so it never has to poll.
    """

    entry_added = Signal(str, str, bool)

    def __init__(self):
        super().__init__()
        self._entries = []

    # ---------- writing ----------
    def info(self, message):
        self._add(message, is_error=False)

    def error(self, message):
        self._add(message, is_error=True)

    def _add(self, message, is_error):
        text = str(message or "").strip()
        if not text:
            return
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._entries.append((timestamp, text, is_error))
        self._write_file(timestamp, text, is_error)
        self.entry_added.emit(timestamp, text, is_error)

    # ---------- reading ----------
    def entries(self):
        """A copy of ``(timestamp, message, is_error)`` tuples."""
        return list(self._entries)

    def clear(self):
        """Drop the in-memory history (the file log is left intact)."""
        self._entries.clear()

    # ---------- persistence ----------
    def _write_file(self, timestamp, message, is_error):
        try:
            log_dir = app_dir() / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            level = "ERROR" if is_error else "INFO"
            with open(log_dir / "consolemode.log", "a", encoding="utf-8") as handle:
                handle.write("%s [%s] %s\n" % (timestamp, level, message))
        except OSError:
            # Logging must never take the app down with it.
            pass
