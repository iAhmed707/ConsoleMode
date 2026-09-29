"""Logs page: a live, timestamped view of the application-wide log."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class LogsPage(QWidget):
    """Shows every entry the LogManager broadcasts, newest at the bottom."""

    def __init__(self, log_manager):
        super().__init__()
        self.log_manager = log_manager

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        title = QLabel("Logs")
        title.setFont(QFont("Segoe UI", 22, QFont.Bold))
        layout.addWidget(title)

        subtitle = QLabel(
            "A timestamped record of profiles, displays, audio, applications "
            "and errors. Errors are highlighted."
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("""
            QTextEdit {
                background: #1E1E1E;
                border: none;
                border-radius: 8px;
                font-family: Consolas, monospace;
                font-size: 11pt;
                color: #D1D5DB;
                padding: 12px;
            }
        """)
        layout.addWidget(self.log_text, 1)

        buttons = QHBoxLayout()
        clear_btn = QPushButton("Clear Logs")
        clear_btn.clicked.connect(self.clear_logs)
        buttons.addWidget(clear_btn)
        buttons.addStretch()
        layout.addLayout(buttons)

        # Replay any entries recorded before this page existed, then follow live.
        for timestamp, message, is_error in self.log_manager.entries():
            self._append(timestamp, message, is_error)
        self.log_manager.entry_added.connect(self._append)

    def _append(self, timestamp, message, is_error):
        if is_error:
            line = ('<span style="color:#6B7280;">[%s]</span> '
                    '<span style="color:#EF4444; font-weight:bold;">ERROR: %s</span>'
                    % (timestamp, message))
        else:
            line = ('<span style="color:#6B7280;">[%s]</span> '
                    '<span style="color:#D1D5DB;">%s</span>'
                    % (timestamp, message))
        self.log_text.append(line)
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def clear_logs(self):
        """Clear the on-screen history (the file log is left intact)."""
        self.log_manager.clear()
        self.log_text.clear()
