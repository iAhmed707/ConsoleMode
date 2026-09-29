"""Hotkeys page: edit global keyboard shortcuts for ConsoleMode actions.

Every action row shows a shortcut editor plus a live status line underneath:
whether the shortcut is currently registered (green), failed to register
(red), or simply not assigned (grey).  While the user types a combination
the line switches to live hints — conflicts with another action, missing
modifier keys, unsupported keys — and Apply updates the status immediately.
"""

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont, QKeySequence
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.managers.hotkey_manager import HotkeyManager
from app.managers.settings_manager import DEFAULT_HOTKEYS, HOTKEY_LABELS

# Status colours, shared with the rest of the UI.
GREEN = "#22C55E"
RED = "#EF4444"
AMBER = "#F59E0B"
GREY = "#9CA3AF"


class HotkeysPage(QWidget):
    """One row per action: a shortcut editor plus its live registration state."""

    status = Signal(str)
    error = Signal(str)

    def __init__(self, hotkey_manager, settings_manager):
        super().__init__()
        self.hotkeys = hotkey_manager
        self.settings = settings_manager
        self._editors = {}
        self._status_labels = {}

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        title = QLabel("Hotkeys")
        title.setFont(QFont("Segoe UI", 22, QFont.Bold))
        layout.addWidget(title)

        subtitle = QLabel(
            "Global keyboard shortcuts that work even when ConsoleMode is not "
            "focused. Click a box, press your combination and press Apply. "
            "Avoid shortcuts that Windows or other programs already use."
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        if not self.hotkeys.is_available():
            unavailable = QLabel(self.hotkeys.unavailable_reason())
            unavailable.setWordWrap(True)
            unavailable.setStyleSheet("color: %s;" % AMBER)
            layout.addWidget(unavailable)
            layout.addStretch()
            return

        header = QHBoxLayout()
        defaults_btn = QPushButton("Restore Defaults")
        defaults_btn.setToolTip(
            "Reset every shortcut to its default combination and register it."
        )
        defaults_btn.clicked.connect(self.restore_defaults)
        header.addStretch()
        header.addWidget(defaults_btn)
        layout.addLayout(header)

        for action, label in HOTKEY_LABELS.items():
            layout.addWidget(self._build_action_row(action, label))

        layout.addStretch()

        self._load_from_settings()
        self.refresh_status()

    def _build_action_row(self, action, label):
        frame = QFrame()
        frame.setObjectName("DetailPanel")
        frame_layout = QVBoxLayout(frame)
        frame_layout.setSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(10)

        name_label = QLabel(label)
        name_label.setFont(QFont("Segoe UI", 11, QFont.Bold))
        name_label.setMinimumWidth(220)
        row.addWidget(name_label)

        editor = QKeySequenceEdit()
        if hasattr(editor, "setMaximumSequenceLength"):
            editor.setMaximumSequenceLength(1)  # one combination, not "A, B"
        if hasattr(editor, "setClearButtonEnabled"):
            editor.setClearButtonEnabled(True)
        editor.setToolTip("Click here, then press the key combination.")
        editor.keySequenceChanged.connect(
            lambda _sequence, a=action: self._on_editor_changed(a)
        )
        row.addWidget(editor, 1)

        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(lambda checked, a=action: self.apply(a))
        row.addWidget(apply_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(lambda checked, a=action: self.clear(a))
        row.addWidget(clear_btn)

        frame_layout.addLayout(row)

        status_line = QHBoxLayout()
        status_line.setSpacing(6)
        status_line.addSpacing(232)  # aligns the status under the editor
        status_label = QLabel("")
        status_label.setWordWrap(True)
        status_line.addWidget(status_label, 1)
        frame_layout.addLayout(status_line)

        self._editors[action] = editor
        self._status_labels[action] = status_label
        return frame

    def _load_from_settings(self):
        configured = self.settings.hotkeys()
        for action, shortcut in configured.items():
            editor = self._editors.get(action)
            if editor is not None:
                editor.setKeySequence(QKeySequence(shortcut))

    # ---------- live feedback ----------
    def _editor_text(self, action):
        return self._editors[action].keySequence().toString(
            QKeySequence.NativeText
        )

    def _on_editor_changed(self, action):
        """Show a hint as soon as the user types a combination."""
        text = self._editor_text(action)
        if not text:
            self._set_status(action, "No shortcut assigned.", GREY)
            return

        parsed = HotkeyManager.parse_sequence(text)
        if parsed is None:
            self._set_status(action, "Unsupported shortcut: %s." % text, RED)
            return

        conflict = self.hotkeys.conflict_for(action, text)
        if conflict is not None:
            label = HOTKEY_LABELS.get(conflict, conflict)
            self._set_status(action, "Already used by '%s'." % label, RED)
            return

        if parsed[0] == 0:
            self._set_status(
                action,
                "No modifier keys — this fires whenever you press %s." % text,
                AMBER,
            )
            return

        self._set_status(action, "Press Apply to activate.", GREY)

    def refresh_status(self):
        """Show the live registration state for every action."""
        for action in self._status_labels:
            state, detail = self.hotkeys.state(action)
            if state == "active":
                self._set_status(
                    action, "Active — %s is registered." % detail, GREEN
                )
                self._set_editor_error(action, False)
            elif state == "failed":
                self._set_status(action, "Not active — %s" % detail, RED)
                self._set_editor_error(action, True)
            else:
                self._set_status(action, "No shortcut assigned.", GREY)
                self._set_editor_error(action, False)

    def _set_status(self, action, message, colour):
        label = self._status_labels[action]
        label.setText("● %s" % message)
        label.setStyleSheet("color: %s;" % colour)

    def _set_editor_error(self, action, failed):
        """Highlight the editor border when its shortcut is not live."""
        editor = self._editors[action]
        editor.setStyleSheet(
            "QKeySequenceEdit { border: 1px solid %s; }"
            % (RED if failed else "#3F3F46")
        )

    # ---------- actions ----------
    def apply(self, action):
        text = self._editor_text(action)
        if not text:
            self._set_status(action, "Press a key combination first.", AMBER)
            self.error.emit("No shortcut entered for '%s'." % HOTKEY_LABELS[action])
            return

        ok, message = self.hotkeys.register_hotkey(action, text)
        if ok:
            self.settings.set_hotkey(action, text)
            self._set_editor_error(action, False)
            self._set_status(action, "Active — %s is registered." % text, GREEN)
            self.status.emit(message)
        else:
            self._set_editor_error(action, True)
            self._set_status(action, message, RED)
            self.error.emit(message)

    def clear(self, action):
        self.hotkeys.unregister(action)
        self._editors[action].clear()
        self.settings.set_hotkey(action, "")
        self._set_editor_error(action, False)
        self._set_status(action, "Shortcut cleared.", GREY)
        self.status.emit("Cleared the shortcut for '%s'." % HOTKEY_LABELS[action])

    def restore_defaults(self):
        """Re-apply every default shortcut and register it."""
        restored = []
        for action, default in DEFAULT_HOTKEYS.items():
            editor = self._editors.get(action)
            if editor is None:
                continue
            editor.setKeySequence(QKeySequence(default))
            ok, message = self.hotkeys.register_hotkey(action, default)
            self.settings.set_hotkey(action, default)
            if ok:
                self._set_editor_error(action, False)
                self._set_status(
                    action, "Active — %s is registered." % default, GREEN
                )
                restored.append(default)
            else:
                self._set_editor_error(action, True)
                self._set_status(action, message, RED)
                self.error.emit(message)
        if restored:
            self.status.emit("Restored default shortcuts: %s." % ", ".join(restored))
