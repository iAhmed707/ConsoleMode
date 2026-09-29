"""Game controller detection via XInput.

XInput is the standard Windows API for Xbox-style controllers and ships with
the OS, so no extra dependency is needed.  It exposes four fixed controller
slots rather than friendly names; the device subtype is mapped to a readable
label ("Gamepad", "Wheel", ...).  The manager is fully optional: when the DLL
cannot be loaded (non-Windows hosts, or a stripped-down Windows install) it
reports "unavailable" instead of failing.
"""

import ctypes
import sys
from ctypes import wintypes

IS_WINDOWS = sys.platform == "win32"

ERROR_DEVICE_NOT_CONNECTED = 1167
XINPUT_FLAG_GAMEPAD = 0x0001
XINPUT_MAX_SLOTS = 4

SUBTYPE_NAMES = {
    1: "Gamepad",
    2: "Wheel",
    3: "Arcade Stick",
    4: "Flight Stick",
    5: "Dance Pad",
    6: "Guitar",
    7: "Guitar (alternate)",
    8: "Drum Kit",
    0x0B: "Bass Guitar",
    0x13: "Arcade Pad",
}


class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ("wButtons", wintypes.WORD),
        ("bLeftTrigger", ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX", ctypes.c_short),
        ("sThumbLY", ctypes.c_short),
        ("sThumbRX", ctypes.c_short),
        ("sThumbRY", ctypes.c_short),
    ]


class XINPUT_STATE(ctypes.Structure):
    _fields_ = [
        ("dwPacketNumber", wintypes.DWORD),
        ("Gamepad", XINPUT_GAMEPAD),
    ]


class XINPUT_VIBRATION(ctypes.Structure):
    _fields_ = [
        ("wLeftMotorSpeed", wintypes.WORD),
        ("wRightMotorSpeed", wintypes.WORD),
    ]


class XINPUT_CAPABILITIES(ctypes.Structure):
    _fields_ = [
        ("Type", ctypes.c_ubyte),
        ("SubType", ctypes.c_ubyte),
        ("Flags", wintypes.WORD),
        ("Gamepad", XINPUT_GAMEPAD),
        ("Vibration", XINPUT_VIBRATION),
    ]


class ControllerManager:
    """Lists XInput-compatible game controllers currently connected."""

    def __init__(self):
        self._dll = self._load_dll()

    def _load_dll(self):
        if not IS_WINDOWS:
            return None
        for name in ("xinput1_4", "xinput9_1_0"):
            try:
                dll = ctypes.WinDLL(name)
                dll.XInputGetState.argtypes = [
                    wintypes.DWORD, ctypes.POINTER(XINPUT_STATE),
                ]
                dll.XInputGetState.restype = wintypes.DWORD
                dll.XInputGetCapabilities.argtypes = [
                    wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(XINPUT_CAPABILITIES),
                ]
                dll.XInputGetCapabilities.restype = wintypes.DWORD
                return dll
            except OSError:
                continue
        return None

    def is_available(self):
        return self._dll is not None

    def unavailable_reason(self):
        if self.is_available():
            return None
        return (
            "Controller detection needs the Windows XInput API, which is not "
            "available in this environment."
        )

    def get_controllers(self):
        """Controller dicts: ``index``, ``name``, ``subtype_name``."""
        if not self._dll:
            return []

        controllers = []
        for index in range(XINPUT_MAX_SLOTS):
            state = XINPUT_STATE()
            if self._dll.XInputGetState(index, ctypes.byref(state)) != 0:
                continue  # empty slot (or another, non-"connected" error)

            subtype = 1
            caps = XINPUT_CAPABILITIES()
            if self._dll.XInputGetCapabilities(
                index, XINPUT_FLAG_GAMEPAD, ctypes.byref(caps)
            ) == 0:
                subtype = caps.SubType or 1

            controllers.append({
                "index": index + 1,
                "name": "Xbox %s" % SUBTYPE_NAMES.get(subtype, "Controller"),
                "subtype_name": SUBTYPE_NAMES.get(subtype, "Unknown"),
            })
        return controllers

    def refresh(self):
        return self.get_controllers()
