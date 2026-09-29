"""Global keyboard shortcuts using the Windows RegisterHotKey API.

Hotkeys are registered against the calling thread's message queue (no window
handle is required) and received through a Qt native event filter, so they stay
active regardless of which window has focus.  The manager is optional: when the
Win32 API is unavailable nothing is registered and callers get a clear reason
instead of a crash.

No system-critical shortcuts are registered by default — the built-in bindings
all require at least two modifiers (Ctrl+Alt) and can be changed or cleared by
the user on the Hotkeys page.

The manager also tracks, per action, whether the shortcut is currently live
(``state``) and detects combinations that collide with another ConsoleMode
action (``conflict_for``), so the Hotkeys page can display the real status
instead of an empty label.
"""

import ctypes
import re
import sys
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

from app.managers.settings_manager import HOTKEY_LABELS

IS_WINDOWS = sys.platform == "win32"

# RegisterHotKey modifier flags
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008

WM_HOTKEY = 0x0312

MODIFIER_NAMES = {
    "ctrl": MOD_CONTROL, "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN, "meta": MOD_WIN, "super": MOD_WIN,
}

# Virtual-key codes for the non-alphanumeric keys users are likely to pick.
KEY_CODES = {
    "SPACE": 0x20, "RETURN": 0x0D, "ENTER": 0x0D, "TAB": 0x09,
    "ESCAPE": 0x1B, "ESC": 0x1B, "BACKSPACE": 0x08,
    "DELETE": 0x2E, "DEL": 0x2E, "INSERT": 0x2D, "INS": 0x2D,
    "HOME": 0x24, "END": 0x23,
    "PAGEUP": 0x21, "PGUP": 0x21, "PAGEDOWN": 0x22, "PGDN": 0x22,
    "LEFT": 0x25, "RIGHT": 0x27, "UP": 0x26, "DOWN": 0x28,
    "PRINTSCREEN": 0x2C, "PAUSE": 0x13, "CAPSLOCK": 0x14,
    "NUMLOCK": 0x90, "SCROLLLOCK": 0x91,
    # Punctuation keys, rendered literally by QKeySequenceEdit ("Ctrl++").
    "+": 0xBB, "=": 0xBB, "-": 0xBD, ",": 0xBC, ".": 0xBE,
    ";": 0xBA, "/": 0xBF, "'": 0xDE, "`": 0xC0,
    "[": 0xDB, "]": 0xDD, "\\": 0xDC, "BACKSLASH": 0xDC,
}


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _MSG(ctypes.Structure):
    """Layout of the Win32 MSG structure Qt hands to native event filters.

    ``wParam``/``lParam`` are pointer-sized, so the explicit ``c_size_t`` /
    ``c_ssize_t`` keep the 64-bit layout correct.
    """

    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_ssize_t),
        ("time", wintypes.DWORD),
        ("pt", _POINT),
    ]


class HotkeySignals(QObject):
    """Qt signals emitted when a registered hotkey fires.

    Kept on a separate QObject because PySide6 does not call the Python
    ``nativeEventFilter`` override on classes that inherit QObject together
    with QAbstractNativeEventFilter (verified on PySide6 6.11).
    """

    toggle_console = Signal()
    exit_console = Signal()
    show_window = Signal()


class HotkeyManager(QAbstractNativeEventFilter):
    """Registers global hotkeys and translates WM_HOTKEY into Qt signals."""

    def __init__(self):
        QAbstractNativeEventFilter.__init__(self)
        self.signals = HotkeySignals()
        self._user32 = ctypes.windll.user32 if IS_WINDOWS else None
        self._registered = {}  # action_id -> (hotkey_id, text)
        self._last_failure = {}  # action_id -> reason the last attempt failed
        self._next_id = 1

        if self._user32:
            self._user32.RegisterHotKey.argtypes = [
                wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT,
            ]
            self._user32.RegisterHotKey.restype = wintypes.BOOL
            self._user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
            self._user32.UnregisterHotKey.restype = wintypes.BOOL

    # ---------- availability ----------
    def is_available(self):
        return self._user32 is not None

    def unavailable_reason(self):
        if self.is_available():
            return None
        return "Global hotkeys are only supported on Windows."

    # ---------- registration ----------
    def register_hotkey(self, action_id, sequence_text):
        """Register (or re-register) one action's shortcut.

        Returns ``(success, message)``.  An empty string unregisters the
        action.  A failed attempt leaves any previous binding untouched.
        """
        sequence_text = (sequence_text or "").strip()
        if not sequence_text:
            self.unregister(action_id)
            return True, "No shortcut assigned to this action."

        if not self.is_available():
            return False, self.unavailable_reason()

        parsed = self.parse_sequence(sequence_text)
        if parsed is None:
            return False, "Unsupported shortcut: %s" % sequence_text

        # Re-applying the combination that is already live is a no-op, so
        # double clicks on Apply don't churn the registration.
        current = self._registered.get(action_id)
        if current is not None and self.parse_sequence(current[1]) == parsed:
            return True, "Already active: %s." % sequence_text

        # Collides with another ConsoleMode action: report it before Windows
        # returns its generic "already in use" error.
        conflict = self.conflict_for(action_id, sequence_text)
        if conflict is not None:
            label = HOTKEY_LABELS.get(conflict, conflict)
            return False, ("%s is already used by '%s' in ConsoleMode."
                           % (sequence_text, label))

        modifiers, vk = parsed
        hotkey_id = self._next_id
        self._next_id += 1

        # hwnd=None posts WM_HOTKEY to this thread's message queue, where the
        # native event filter below picks it up.  The new binding is
        # registered before the old one is released, so a failure keeps the
        # previous shortcut working.
        if not self._user32.RegisterHotKey(None, hotkey_id, modifiers, vk):
            message = ("Could not register %s — it may already be in use "
                       "by another program." % sequence_text)
            if action_id not in self._registered:
                self._last_failure[action_id] = message
            return False, message

        if current is not None:
            self._user32.UnregisterHotKey(None, current[0])
        self._registered[action_id] = (hotkey_id, sequence_text)
        self._last_failure.pop(action_id, None)
        return True, "Registered %s." % sequence_text

    def unregister(self, action_id):
        self._last_failure.pop(action_id, None)
        if not self._user32 or action_id not in self._registered:
            self._registered.pop(action_id, None)
            return
        hotkey_id, _ = self._registered.pop(action_id)
        self._user32.UnregisterHotKey(None, hotkey_id)

    def unregister_all(self):
        """Release every hotkey. Safe to call more than once."""
        for action_id in list(self._registered):
            self.unregister(action_id)

    def registered(self):
        """A dict of ``action_id -> sequence_text`` for the UI."""
        return {key: value[1] for key, value in self._registered.items()}

    def is_registered(self, action_id):
        return action_id in self._registered

    # ---------- status for the UI ----------
    def state(self, action_id):
        """``(state, detail)`` describing one action.

        ``active`` means the combination is live (detail = combo text),
        ``failed`` means the last attempt could not be registered (detail =
        the reason) and ``unassigned`` means no shortcut is configured.
        """
        if action_id in self._registered:
            return "active", self._registered[action_id][1]
        failure = self._last_failure.get(action_id)
        if failure:
            return "failed", failure
        return "unassigned", ""

    def conflict_for(self, action_id, sequence_text):
        """The other action already using ``sequence_text``, or None.

        Comparison is on the parsed ``(modifiers, key)`` pair, so "Ctrl+Alt+L"
        and "Alt+Ctrl+L" are recognised as the same combination.
        """
        parsed = self.parse_sequence(sequence_text)
        if parsed is None:
            return None
        for other, (_hotkey_id, other_text) in self._registered.items():
            if other == action_id:
                continue
            if self.parse_sequence(other_text) == parsed:
                return other
        return None

    # ---------- native event handling ----------
    def nativeEventFilter(self, event_type, message):
        if not self._user32 or not self._registered:
            return False, 0

        try:
            msg = ctypes.cast(int(message), ctypes.POINTER(_MSG)).contents
        except (ValueError, TypeError, OSError):
            return False, 0

        if msg.message != WM_HOTKEY:
            return False, 0

        for action_id, (hotkey_id, _text) in list(self._registered.items()):
            if msg.wParam == hotkey_id:
                self._emit_action(action_id)
                return True, 0
        return False, 0

    def _emit_action(self, action_id):
        signal = {
            "toggle_console": self.signals.toggle_console,
            "exit_console": self.signals.exit_console,
            "show_window": self.signals.show_window,
        }.get(action_id)
        if signal is not None:
            signal.emit()

    # ---------- parsing ----------
    @staticmethod
    def parse_sequence(text):
        """``"Ctrl+Alt+L"`` -> ``(modifiers, vk)``, or None if unsupported.

        Modifier order and casing are free, and punctuation keys such as
        ``"Ctrl++"`` (the plus key) are supported.
        """
        text = (text or "").strip()
        if not text:
            return None

        parts = [part.strip() for part in text.split("+")]
        modifiers = 0
        key_token = None
        for part in parts:
            if not part:
                continue
            lowered = part.lower()
            if lowered in MODIFIER_NAMES:
                modifiers |= MODIFIER_NAMES[lowered]
            elif key_token is None:
                key_token = part
            else:
                return None  # only one non-modifier key is supported

        if key_token is None:
            # "Ctrl++" splits into ["Ctrl", "", ""]: the key is the plus sign.
            key_token = "+" if text.endswith("+") else None
        if key_token is None:
            return None

        vk = HotkeyManager._key_to_vk(key_token)
        if vk is None:
            return None
        return modifiers, vk

    @staticmethod
    def _key_to_vk(token):
        token = token.strip()
        if len(token) == 1:
            if token.isalpha():
                return ord(token.upper())
            if token.isdigit():
                return ord(token)

        upper = token.upper()
        if upper in KEY_CODES:
            return KEY_CODES[upper]

        match = re.fullmatch(r"F([1-9]|1[0-9]|2[0-4])", upper)
        if match:
            return 0x6F + int(match.group(1))  # VK_F1 == 0x70
        return None
