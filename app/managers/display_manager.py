"""Display detection and control.

Monitors are enumerated with the Windows display API (via ``ctypes``) so we get
the adapter device name (``\\\\.\\DISPLAY1``) that ``ChangeDisplaySettingsEx``
needs.  ``screeninfo`` is kept as a read-only fallback for when the native path
is unavailable (non-Windows dev machines, unexpected API failures).

No new dependencies: everything Windows-specific goes through ``ctypes``.
"""

import ctypes
import re
import sys
from ctypes import wintypes

IS_WINDOWS = sys.platform == "win32"

# ---------- Win32 structures ----------
class POINTL(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_long),
        ("y", ctypes.c_long),
    ]

class DEVMODE(ctypes.Structure):
    """DEVMODEW, laid out with the *display* half of its unions."""

    _fields_ = [
        ("dmDeviceName", wintypes.WCHAR * 32),
        ("dmSpecVersion", wintypes.WORD),
        ("dmDriverVersion", wintypes.WORD),
        ("dmSize", wintypes.WORD),
        ("dmDriverExtra", wintypes.WORD),
        ("dmFields", wintypes.DWORD),
        # union: printer orientation fields / display position fields
        ("dmPosition", POINTL),
        ("dmDisplayOrientation", wintypes.DWORD),
        ("dmDisplayFixedOutput", wintypes.DWORD),
        ("dmColor", ctypes.c_short),
        ("dmDuplex", ctypes.c_short),
        ("dmYResolution", ctypes.c_short),
        ("dmTTOption", ctypes.c_short),
        ("dmCollate", ctypes.c_short),
        ("dmFormName", wintypes.WCHAR * 32),
        ("dmLogPixels", wintypes.WORD),
        ("dmBitsPerPel", wintypes.DWORD),
        ("dmPelsWidth", wintypes.DWORD),
        ("dmPelsHeight", wintypes.DWORD),
        ("dmDisplayFlags", wintypes.DWORD),  # union with dmNup
        ("dmDisplayFrequency", wintypes.DWORD),
        ("dmICMMethod", wintypes.DWORD),
        ("dmICMIntent", wintypes.DWORD),
        ("dmMediaType", wintypes.DWORD),
        ("dmDitherType", wintypes.DWORD),
        ("dmReserved1", wintypes.DWORD),
        ("dmReserved2", wintypes.DWORD),
        ("dmPanningWidth", wintypes.DWORD),
        ("dmPanningHeight", wintypes.DWORD),
    ]

class DISPLAY_DEVICE(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("DeviceName", wintypes.WCHAR * 32),
        ("DeviceString", wintypes.WCHAR * 128),
        ("StateFlags", wintypes.DWORD),
        ("DeviceID", wintypes.WCHAR * 128),
        ("DeviceKey", wintypes.WCHAR * 128),
    ]

# ---------- Win32 CCD (Connecting and Configuring Displays) structures ----------
# The legacy EnumDisplaySettings API knows nothing about HDR or the real
# monitor name, so those come from QueryDisplayConfig instead.
class LUID(ctypes.Structure):
    _fields_ = [
        ("LowPart", wintypes.DWORD),
        ("HighPart", ctypes.c_long),
    ]

class DISPLAYCONFIG_RATIONAL(ctypes.Structure):
    """Exact refresh rate, e.g. 239760 / 1000 = 239.76 Hz."""

    _fields_ = [
        ("Numerator", wintypes.DWORD),
        ("Denominator", wintypes.DWORD),
    ]

    def as_hz(self):
        if not self.Denominator:
            return 0.0
        return self.Numerator / self.Denominator

class DISPLAYCONFIG_PATH_SOURCE_INFO(ctypes.Structure):
    _fields_ = [
        ("adapterId", LUID),
        ("id", wintypes.DWORD),
        ("modeInfoIdx", wintypes.DWORD),
        ("statusFlags", wintypes.DWORD),
    ]

class DISPLAYCONFIG_PATH_TARGET_INFO(ctypes.Structure):
    _fields_ = [
        ("adapterId", LUID),
        ("id", wintypes.DWORD),
        ("modeInfoIdx", wintypes.DWORD),
        ("outputTechnology", wintypes.DWORD),
        ("rotation", wintypes.DWORD),
        ("scaling", wintypes.DWORD),
        ("refreshRate", DISPLAYCONFIG_RATIONAL),
        ("scanLineOrdering", wintypes.DWORD),
        ("targetAvailable", wintypes.BOOL),
        ("statusFlags", wintypes.DWORD),
    ]

class DISPLAYCONFIG_PATH_INFO(ctypes.Structure):
    _fields_ = [
        ("sourceInfo", DISPLAYCONFIG_PATH_SOURCE_INFO),
        ("targetInfo", DISPLAYCONFIG_PATH_TARGET_INFO),
        ("flags", wintypes.DWORD),
    ]

class DISPLAYCONFIG_2DREGION(ctypes.Structure):
    _fields_ = [
        ("cx", wintypes.DWORD),
        ("cy", wintypes.DWORD),
    ]

class DISPLAYCONFIG_VIDEO_SIGNAL_INFO(ctypes.Structure):
    """The target/timing half of a display mode: pixel rate, sync and size."""

    _fields_ = [
        ("pixelRate", ctypes.c_uint64),
        ("hSyncFreq", DISPLAYCONFIG_RATIONAL),
        ("vSyncFreq", DISPLAYCONFIG_RATIONAL),
        ("activeSize", DISPLAYCONFIG_2DREGION),
        ("totalSize", DISPLAYCONFIG_2DREGION),
        ("videoStandard", wintypes.DWORD),
        ("scanLineOrdering", wintypes.DWORD),
    ]

class DISPLAYCONFIG_SOURCE_MODE(ctypes.Structure):
    """The geometry half of a display mode: resolution, pixel format, position.

    In CCD a monitor's position lives here, and the primary monitor is simply
    the one whose source mode sits at (0, 0).
    """

    _fields_ = [
        ("width", wintypes.DWORD),
        ("height", wintypes.DWORD),
        ("pixelFormat", wintypes.DWORD),
        ("position", POINTL),
    ]

class DISPLAYCONFIG_TARGET_MODE(ctypes.Structure):
    _fields_ = [
        ("targetVideoSignalInfo", DISPLAYCONFIG_VIDEO_SIGNAL_INFO),
    ]

class DISPLAYCONFIG_MODE_INFO_UNION(ctypes.Union):
    _fields_ = [
        ("sourceMode", DISPLAYCONFIG_SOURCE_MODE),
        ("targetMode", DISPLAYCONFIG_TARGET_MODE),
    ]

class DISPLAYCONFIG_MODE_INFO(ctypes.Structure):
    """One entry of the mode-info array returned by QueryDisplayConfig.

    The layout is ``infoType | id | adapterId | union`` (64 bytes); the union
    holds either a source mode (position + resolution) or a target mode
    (timing/refresh). ``infoType`` selects which member is valid.
    """

    _fields_ = [
        ("infoType", wintypes.DWORD),
        ("id", wintypes.DWORD),
        ("adapterId", LUID),
        ("u", DISPLAYCONFIG_MODE_INFO_UNION),
    ]

class DISPLAYCONFIG_DEVICE_INFO_HEADER(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("size", wintypes.DWORD),
        ("adapterId", LUID),
        ("id", wintypes.DWORD),
    ]

class DISPLAYCONFIG_SOURCE_DEVICE_NAME(ctypes.Structure):
    """Maps a CCD path back to a GDI name such as ``\\\\.\\DISPLAY1``."""

    _fields_ = [
        ("header", DISPLAYCONFIG_DEVICE_INFO_HEADER),
        ("viewGdiDeviceName", wintypes.WCHAR * 32),
    ]

class DISPLAYCONFIG_TARGET_DEVICE_NAME(ctypes.Structure):
    """The real monitor name, e.g. "LG TV SSCR2" rather than "Generic PnP Monitor"."""

    _fields_ = [
        ("header", DISPLAYCONFIG_DEVICE_INFO_HEADER),
        ("flags", wintypes.DWORD),
        ("outputTechnology", wintypes.DWORD),
        ("edidManufactureId", wintypes.WORD),
        ("edidProductCodeId", wintypes.WORD),
        ("connectorInstance", wintypes.DWORD),
        ("monitorFriendlyDeviceName", wintypes.WCHAR * 64),
        ("monitorDevicePath", wintypes.WCHAR * 128),
    ]

class DISPLAYCONFIG_ADVANCED_COLOR_INFO(ctypes.Structure):
    """Windows 10 / early Windows 11 HDR query (info type 9).

    ``value`` is a bitfield; it is read as a plain DWORD and masked below.
    """

    _fields_ = [
        ("header", DISPLAYCONFIG_DEVICE_INFO_HEADER),
        ("value", wintypes.DWORD),
        ("colorEncoding", wintypes.DWORD),
        ("bitsPerColorChannel", wintypes.DWORD),
    ]

class DISPLAYCONFIG_SET_ADVANCED_COLOR_STATE(ctypes.Structure):
    """Turns HDR on or off (info type 10, or type 14 on Windows 11 24H2+).

    Both requests share this layout: a header plus a bitfield whose lowest bit
    is the enable flag.
    """

    _fields_ = [
        ("header", DISPLAYCONFIG_DEVICE_INFO_HEADER),
        ("value", wintypes.DWORD),
    ]

class DISPLAYCONFIG_ADVANCED_COLOR_INFO_2(ctypes.Structure):
    """Windows 11 24H2+ HDR query (info type 13).

    Preferred because type 9 conflates HDR with wide-colour-gamut support,
    so it reports "supported" for displays that are only WCG-capable.
    """

    _fields_ = [
        ("header", DISPLAYCONFIG_DEVICE_INFO_HEADER),
        ("value", wintypes.DWORD),
        ("activeColorMode", wintypes.DWORD),
    ]

# ---------- Win32 constants ----------
ENUM_CURRENT_SETTINGS = -1

DISPLAY_DEVICE_ATTACHED_TO_DESKTOP = 0x00000001
DISPLAY_DEVICE_PRIMARY_DEVICE = 0x00000004
DISPLAY_DEVICE_MIRRORING_DRIVER = 0x00000008

DM_POSITION = 0x00000020
DM_BITSPERPEL = 0x00040000
DM_PELSWIDTH = 0x00080000
DM_PELSHEIGHT = 0x00100000
DM_DISPLAYFREQUENCY = 0x00400000

CDS_UPDATEREGISTRY = 0x00000001
CDS_SET_PRIMARY = 0x00000010
CDS_NORESET = 0x10000000

# CCD API
ERROR_SUCCESS = 0
QDC_ONLY_ACTIVE_PATHS = 0x00000002

DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME = 1
DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME = 2
DISPLAYCONFIG_DEVICE_INFO_GET_ADVANCED_COLOR_INFO = 9
DISPLAYCONFIG_DEVICE_INFO_SET_ADVANCED_COLOR_STATE = 10
DISPLAYCONFIG_DEVICE_INFO_GET_ADVANCED_COLOR_INFO_2 = 13
DISPLAYCONFIG_DEVICE_INFO_SET_HDR_STATE = 14

# Bits of DISPLAYCONFIG_ADVANCED_COLOR_INFO.value (info type 9)
ADVANCED_COLOR_SUPPORTED = 1 << 0
ADVANCED_COLOR_ENABLED = 1 << 1

# Bits of DISPLAYCONFIG_ADVANCED_COLOR_INFO_2.value (info type 13)
HDR_SUPPORTED_2 = 1 << 4
HDR_USER_ENABLED_2 = 1 << 5

# DISPLAYCONFIG_ADVANCED_COLOR_MODE
COLOR_MODE_NAMES = {0: "SDR", 1: "WCG", 2: "HDR"}

# DISPLAYCONFIG_VIDEO_OUTPUT_TECHNOLOGY values worth naming in the UI
OUTPUT_TECHNOLOGY_NAMES = {
    0: "VGA",
    4: "DVI",
    5: "HDMI",
    10: "DisplayPort",
    11: "Internal",
    0x80000000: "Internal",
}

# SetDisplayConfig flags. The modern CCD API applies positions + primary in a
# single driver call, which the legacy ChangeDisplaySettingsEx path cannot do
# reliably across displays with different refresh rates.
SDC_TOPOLOGY_INTERNAL = 0x00000001
SDC_TOPOLOGY_CLONE = 0x00000002
SDC_TOPOLOGY_EXTEND = 0x00000004
SDC_TOPOLOGY_EXTERNAL = 0x00000008
SDC_TOPOLOGY_SUPPLIED = 0x00000010
SDC_USE_SUPPLIED_DISPLAY_CONFIG = 0x00000020
SDC_APPLY = 0x00000080
SDC_SAVE_TO_DATABASE = 0x00000100
SDC_ALLOW_CHANGES = 0x00000400
SDC_PATH_PERSIST_IF_REQUIRED = 0x00000800

# DISPLAYCONFIG_MODE_INFO_TYPE values
DISPLAYCONFIG_MODE_INFO_TYPE_SOURCE = 1
DISPLAYCONFIG_MODE_INFO_TYPE_TARGET = 2

# SetDisplayConfig / QueryDisplayConfig error codes
ERROR_INVALID_PARAMETER = 87
ERROR_NOT_SUPPORTED = 50
ERROR_INSUFFICIENT_BUFFER = 122

DISP_CHANGE_MESSAGES = {
    0: "Success.",
    1: "The settings were applied but a restart is required.",
    -1: "The graphics driver rejected the change.",
    -2: "The requested display mode is not supported.",
    -3: "Unable to write the settings to the registry.",
    -4: "Invalid flags were passed to the display API.",
    -5: "Invalid parameters were passed to the display API.",
    -6: "The display is part of a mirroring/dual-view set that cannot change.",
}

def _win_error(code):
    """Human-readable text for a ChangeDisplaySettingsEx return code."""
    return DISP_CHANGE_MESSAGES.get(code, "Unknown display error (code %s)." % code)

def _sdc_error(code):
    """Human-readable text for a SetDisplayConfig return code."""
    messages = {
        ERROR_SUCCESS: "Success.",
        ERROR_INVALID_PARAMETER: "Windows rejected the display topology.",
        ERROR_NOT_SUPPORTED: "The display driver does not support this topology.",
        ERROR_INSUFFICIENT_BUFFER: "Could not read the current display topology.",
    }
    return messages.get(code, "Unknown display error (code %s)." % code)

class DisplayManager:
    """Detects monitors and applies display layouts.

    Call :meth:`refresh` before reading monitor data; every getter serves the
    snapshot taken by the last refresh so the UI never re-enumerates mid-paint.
    """

    def __init__(self):
        self._monitors = []
        self._user32 = ctypes.windll.user32 if IS_WINDOWS else None
        if self._user32:
            self._declare_prototypes()

    # ---------- setup ----------
    def _declare_prototypes(self):
        """Pin argtypes/restypes so pointers are not truncated on 64-bit."""
        u = self._user32

        u.EnumDisplayDevicesW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(DISPLAY_DEVICE), wintypes.DWORD
        ]
        u.EnumDisplayDevicesW.restype = wintypes.BOOL

        u.EnumDisplaySettingsW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(DEVMODE)
        ]
        u.EnumDisplaySettingsW.restype = wintypes.BOOL

        u.ChangeDisplaySettingsExW.argtypes = [
            wintypes.LPCWSTR, ctypes.POINTER(DEVMODE), wintypes.HWND,
            wintypes.DWORD, wintypes.LPVOID,
        ]
        u.ChangeDisplaySettingsExW.restype = ctypes.c_long

        u.GetDisplayConfigBufferSizes.argtypes = [
            wintypes.UINT, ctypes.POINTER(wintypes.UINT), ctypes.POINTER(wintypes.UINT)
        ]
        u.GetDisplayConfigBufferSizes.restype = ctypes.c_long

        u.QueryDisplayConfig.argtypes = [
            wintypes.UINT,
            ctypes.POINTER(wintypes.UINT), ctypes.POINTER(DISPLAYCONFIG_PATH_INFO),
            ctypes.POINTER(wintypes.UINT), ctypes.POINTER(DISPLAYCONFIG_MODE_INFO),
            wintypes.LPVOID,
        ]
        u.QueryDisplayConfig.restype = ctypes.c_long

        u.DisplayConfigGetDeviceInfo.argtypes = [ctypes.c_void_p]
        u.DisplayConfigGetDeviceInfo.restype = ctypes.c_long

        u.DisplayConfigSetDeviceInfo.argtypes = [ctypes.c_void_p]
        u.DisplayConfigSetDeviceInfo.restype = ctypes.c_long

        # SetDisplayConfig: apply a supplied topology (paths + modes) atomically.
        u.SetDisplayConfig.argtypes = [
            wintypes.UINT, ctypes.POINTER(DISPLAYCONFIG_PATH_INFO),
            wintypes.UINT, ctypes.POINTER(DISPLAYCONFIG_MODE_INFO),
            wintypes.UINT,
        ]
        u.SetDisplayConfig.restype = ctypes.c_long

    # ---------- detection ----------
    def refresh(self):
        """Re-enumerate the attached monitors. Returns the monitor list."""
        if self._user32:
            self._monitors = self._enumerate_native()
        else:
            self._monitors = self._enumerate_screeninfo()
        return self._monitors

    def get_monitor_info(self):
        """Monitor dicts for the UI.

        Each dict: ``id``, ``name``, ``label``, ``width``, ``height``, ``x``,
        ``y``, ``refresh_rate``, ``bits_per_pixel``, ``is_primary``.
        """
        if not self._monitors:
            self.refresh()
        return self._monitors

    def get_monitor(self, device_name):
        """Look up a single monitor by its ``\\\\.\\DISPLAYn`` device name."""
        for mon in self.get_monitor_info():
            if mon["name"] == device_name:
                return mon
        return None

    def get_primary(self):
        for mon in self.get_monitor_info():
            if mon["is_primary"]:
                return mon
        return None

    def _enumerate_native(self):
        """Walk the display adapters with EnumDisplayDevices/EnumDisplaySettings."""
        monitors = []
        index = 0

        # Queried once for all monitors; the CCD API is comparatively slow.
        config = self._query_display_config()

        while True:
            device = DISPLAY_DEVICE()
            device.cb = ctypes.sizeof(DISPLAY_DEVICE)
            if not self._user32.EnumDisplayDevicesW(None, index, ctypes.byref(device), 0):
                break
            index += 1

            # Only monitors that are actually part of the desktop can be posed
            # or resized; pseudo/mirroring adapters would corrupt the layout.
            if not device.StateFlags & DISPLAY_DEVICE_ATTACHED_TO_DESKTOP:
                continue
            if device.StateFlags & DISPLAY_DEVICE_MIRRORING_DRIVER:
                continue

            devmode = self._current_devmode(device.DeviceName)
            if devmode is None:
                continue

            extra = config.get(device.DeviceName, {})

            monitors.append({
                "id": self._id_from_device_name(device.DeviceName, len(monitors)),
                "name": device.DeviceName,
                # The CCD name is the real product name; EnumDisplayDevices
                # usually only offers "Generic PnP Monitor".
                "label": (extra.get("monitor_name")
                          or self._friendly_label(device.DeviceName)
                          or device.DeviceString),
                "width": int(devmode.dmPelsWidth),
                "height": int(devmode.dmPelsHeight),
                "x": int(devmode.dmPosition.x),
                "y": int(devmode.dmPosition.y),
                "refresh_rate": int(devmode.dmDisplayFrequency),
                "refresh_rate_exact": extra.get("refresh_rate_exact"),
                "bits_per_pixel": int(devmode.dmBitsPerPel),
                "connection": extra.get("connection"),
                "hdr_supported": extra.get("hdr_supported"),
                "hdr_enabled": extra.get("hdr_enabled", False),
                "color_mode": extra.get("color_mode"),
                "bits_per_color": extra.get("bits_per_color"),
                "is_primary": bool(device.StateFlags & DISPLAY_DEVICE_PRIMARY_DEVICE),
            })

        return monitors

    def _enumerate_screeninfo(self):
        """Read-only fallback used when the native API is unavailable."""
        try:
            from screeninfo import get_monitors
        except Exception:
            return []

        monitors = []
        for i, mon in enumerate(get_monitors()):
            name = getattr(mon, "name", None) or "\\\\.\\DISPLAY%d" % (i + 1)
            monitors.append({
                "id": self._id_from_device_name(name, i),
                "name": name,
                "label": name,
                "width": mon.width,
                "height": mon.height,
                "x": mon.x,
                "y": mon.y,
                "refresh_rate": 0,
                "refresh_rate_exact": None,
                "bits_per_pixel": 32,
                # screeninfo cannot see any of this; None means "unknown"
                # rather than "not supported".
                "connection": None,
                "hdr_supported": None,
                "hdr_enabled": False,
                "color_mode": None,
                "bits_per_color": None,
                "is_primary": bool(getattr(mon, "is_primary", False)),
            })
        return monitors

    # ---------- HDR / colour info (CCD API) ----------
    def _device_info(self, struct, info_type, adapter_id, target_id):
        """Fill a DISPLAYCONFIG_*_DEVICE_INFO struct. Returns True on success."""
        struct.header.type = info_type
        struct.header.size = ctypes.sizeof(struct)
        struct.header.adapterId = adapter_id
        struct.header.id = target_id
        result = self._user32.DisplayConfigGetDeviceInfo(
            ctypes.cast(ctypes.pointer(struct), ctypes.c_void_p)
        )
        return result == ERROR_SUCCESS

    def _query_display_config(self):
        """Extra per-monitor facts keyed by GDI device name.

        Returns ``{"\\\\.\\DISPLAY1": {...}}`` with the real monitor name,
        connector type, exact refresh rate and HDR state. Returns ``{}`` if the
        CCD API is unavailable, so callers must treat every key as optional.
        """
        if not self._user32:
            return {}

        path_count = wintypes.UINT()
        mode_count = wintypes.UINT()
        if self._user32.GetDisplayConfigBufferSizes(
            QDC_ONLY_ACTIVE_PATHS, ctypes.byref(path_count), ctypes.byref(mode_count)
        ) != ERROR_SUCCESS:
            return {}

        paths = (DISPLAYCONFIG_PATH_INFO * path_count.value)()
        modes = (DISPLAYCONFIG_MODE_INFO * mode_count.value)()
        if self._user32.QueryDisplayConfig(
            QDC_ONLY_ACTIVE_PATHS,
            ctypes.byref(path_count), paths,
            ctypes.byref(mode_count), modes,
            None,
        ) != ERROR_SUCCESS:
            return {}

        info = {}
        for path in paths[:path_count.value]:
            source = DISPLAYCONFIG_SOURCE_DEVICE_NAME()
            if not self._device_info(
                source, DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME,
                path.sourceInfo.adapterId, path.sourceInfo.id,
            ):
                continue

            device_name = source.viewGdiDeviceName
            if not device_name:
                continue

            entry = {
                "refresh_rate_exact": path.targetInfo.refreshRate.as_hz(),
                "connection": OUTPUT_TECHNOLOGY_NAMES.get(
                    path.targetInfo.outputTechnology, "Unknown"
                ),
                # Needed to address this monitor when setting HDR. Copied out
                # of the paths array, which is freed when this call returns.
                "adapter_id": LUID.from_buffer_copy(path.targetInfo.adapterId),
                "target_id": int(path.targetInfo.id),
            }

            target = DISPLAYCONFIG_TARGET_DEVICE_NAME()
            if self._device_info(
                target, DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME,
                path.targetInfo.adapterId, path.targetInfo.id,
            ):
                entry["monitor_name"] = target.monitorFriendlyDeviceName or None

            entry.update(self._query_hdr(
                path.targetInfo.adapterId, path.targetInfo.id
            ))
            info[device_name] = entry

        return info

    def _query_hdr(self, adapter_id, target_id):
        """HDR support/state for one target.

        Tries the Windows 11 24H2+ query first because the older one reports
        wide-colour-gamut displays as HDR-capable; falls back to the older one
        on earlier builds.
        """
        unknown = {
            "hdr_supported": None,
            "hdr_enabled": False,
            "color_mode": None,
            "bits_per_color": None,
        }

        advanced2 = DISPLAYCONFIG_ADVANCED_COLOR_INFO_2()
        if self._device_info(
            advanced2, DISPLAYCONFIG_DEVICE_INFO_GET_ADVANCED_COLOR_INFO_2,
            adapter_id, target_id,
        ):
            return {
                "hdr_supported": bool(advanced2.value & HDR_SUPPORTED_2),
                "hdr_enabled": bool(advanced2.value & HDR_USER_ENABLED_2),
                "color_mode": COLOR_MODE_NAMES.get(advanced2.activeColorMode),
                "bits_per_color": None,
            }

        advanced = DISPLAYCONFIG_ADVANCED_COLOR_INFO()
        if self._device_info(
            advanced, DISPLAYCONFIG_DEVICE_INFO_GET_ADVANCED_COLOR_INFO,
            adapter_id, target_id,
        ):
            enabled = bool(advanced.value & ADVANCED_COLOR_ENABLED)
            return {
                "hdr_supported": bool(advanced.value & ADVANCED_COLOR_SUPPORTED),
                "hdr_enabled": enabled,
                "color_mode": "HDR" if enabled else "SDR",
                "bits_per_color": int(advanced.bitsPerColorChannel) or None,
            }

        return unknown

    def set_hdr(self, device_name, enabled):
        """Turn HDR on or off for one monitor. Returns ``(success, message)``.

        LUIDs are re-queried here rather than cached, because they change when
        displays are reconnected or the desktop is reconfigured.
        """
        if not self._user32:
            return False, "Display changes are only supported on Windows."

        entry = self._query_display_config().get(device_name)
        if entry is None:
            return False, "Display %s is not attached." % device_name
        if entry.get("hdr_supported") is False:
            return False, "%s does not support HDR." % device_name

        state = DISPLAYCONFIG_SET_ADVANCED_COLOR_STATE()
        state.value = 1 if enabled else 0

        # Type 14 is the modern request; type 10 covers older builds. Both use
        # the same struct, so only the header type differs.
        for info_type in (DISPLAYCONFIG_DEVICE_INFO_SET_HDR_STATE,
                          DISPLAYCONFIG_DEVICE_INFO_SET_ADVANCED_COLOR_STATE):
            state.header.type = info_type
            state.header.size = ctypes.sizeof(state)
            state.header.adapterId = entry["adapter_id"]
            state.header.id = entry["target_id"]

            if self._user32.DisplayConfigSetDeviceInfo(
                ctypes.cast(ctypes.pointer(state), ctypes.c_void_p)
            ) == ERROR_SUCCESS:
                self.refresh()
                return True, "HDR %s for %s." % (
                    "enabled" if enabled else "disabled", device_name
                )

        return False, "Windows rejected the HDR change for %s." % device_name

    def _current_devmode(self, device_name):
        """Current DEVMODE for an adapter, or None if it cannot be read."""
        devmode = DEVMODE()
        devmode.dmSize = ctypes.sizeof(DEVMODE)
        ok = self._user32.EnumDisplaySettingsW(
            device_name, ENUM_CURRENT_SETTINGS, ctypes.byref(devmode)
        )
        return devmode if ok else None

    def _friendly_label(self, device_name):
        """The monitor's marketing name, e.g. "LG TV SSCR2"."""
        monitor = DISPLAY_DEVICE()
        monitor.cb = ctypes.sizeof(DISPLAY_DEVICE)
        if self._user32.EnumDisplayDevicesW(device_name, 0, ctypes.byref(monitor), 0):
            return monitor.DeviceString
        return None

    @staticmethod
    def _id_from_device_name(device_name, fallback_index):
        """``\\\\.\\DISPLAY3`` -> 3, so ids stay stable across refreshes."""
        match = re.search(r"(\d+)\s*$", device_name or "")
        return int(match.group(1)) if match else fallback_index + 1

    # ---------- available modes ----------
    def get_available_modes(self, device_name):
        """Every mode the adapter reports, as ``(width, height, refresh)`` tuples.

        Deduplicated and sorted largest-first so the UI can bind it straight to
        a dropdown.
        """
        if not self._user32:
            return []

        modes = set()
        mode_index = 0
        while True:
            devmode = DEVMODE()
            devmode.dmSize = ctypes.sizeof(DEVMODE)
            if not self._user32.EnumDisplaySettingsW(
                device_name, mode_index, ctypes.byref(devmode)
            ):
                break
            mode_index += 1
            # 8/16-bit modes are legacy noise for a gaming setup.
            if devmode.dmBitsPerPel >= 32:
                modes.add((
                    int(devmode.dmPelsWidth),
                    int(devmode.dmPelsHeight),
                    int(devmode.dmDisplayFrequency),
                ))

        return sorted(modes, reverse=True)

    # ---------- applying changes ----------
    def set_resolution(self, device_name, width, height, refresh_rate=None):
        """Change one monitor's mode, leaving its position untouched.

        Falls back to SetDisplayConfig when the legacy call is rejected, which
        happens on HDR-enabled displays. Returns ``(success, message)``.
        """
        if not self._user32:
            return False, "Display changes are only supported on Windows."

        devmode = self._current_devmode(device_name)
        if devmode is None:
            return False, "Display %s is not attached." % device_name

        devmode.dmPelsWidth = width
        devmode.dmPelsHeight = height
        devmode.dmFields = DM_PELSWIDTH | DM_PELSHEIGHT | DM_BITSPERPEL
        if refresh_rate:
            devmode.dmDisplayFrequency = refresh_rate
            devmode.dmFields |= DM_DISPLAYFREQUENCY

        code = self._user32.ChangeDisplaySettingsExW(
            device_name, ctypes.byref(devmode), None, CDS_UPDATEREGISTRY, None
        )
        if code < 0 and self._apply_mode_via_ccd(
            device_name, width, height, refresh_rate or 0
        ):
            code = 0
        self.refresh()
        return code >= 0, _win_error(code)

    def set_primary(self, device_name):
        """Make one monitor primary, keeping every monitor's relative position.

        Windows requires the primary monitor to sit at (0, 0), so the whole
        desktop is translated by the new primary's offset before committing.
        """
        if not self._user32:
            return False, "Display changes are only supported on Windows."

        monitors = self.refresh()
        target = next((m for m in monitors if m["name"] == device_name), None)
        if target is None:
            return False, "Display %s is not attached." % device_name
        if target["is_primary"]:
            return True, "%s is already the primary display." % device_name

        layout = [dict(m) for m in monitors]
        for mon in layout:
            mon["is_primary"] = mon["name"] == device_name

        return self.apply_layout(layout)

    def apply_layout(self, monitors):
        """Apply a full layout (position, resolution, primary).

        ``monitors`` is a list of dicts as produced by :meth:`capture_layout`.

        Positions (and therefore which monitor is primary) go through
        ``SetDisplayConfig``, which applies the whole topology atomically and is
        the only path that promotes a primary across monitors with different
        refresh rates.  Resolution/refresh changes follow per monitor and are
        reported without undoing the position switch: a rejected mode change
        must never leave the desktop on the wrong primary, which used to make
        every launched application open on the wrong screen.

        A layout that already matches the live one is a no-op (no driver call),
        because staging identical settings has been observed to be rejected by
        drivers.

        Returns ``(success, message)``.
        """
        if not self._user32:
            return False, "Display changes are only supported on Windows."
        if not monitors:
            return False, "The profile does not contain any display settings."

        attached = {m["name"] for m in self.refresh()}
        wanted = [m for m in monitors if m.get("name") in attached]
        missing = [m.get("name") for m in monitors if m.get("name") not in attached]
        if not wanted:
            return False, "None of the profile's displays are currently connected."

        primary = next((m for m in wanted if m.get("is_primary")), wanted[0])
        offset_x, offset_y = int(primary.get("x", 0)), int(primary.get("y", 0))

        # Final position of every monitor once `primary` sits at (0, 0).
        positions = {
            m["name"]: (int(m.get("x", 0)) - offset_x, int(m.get("y", 0)) - offset_y)
            for m in wanted
        }

        if self._layout_is_current(wanted, positions):
            self.refresh()
            return True, "Display layout already matches the profile."

        # Positions + primary in one atomic CCD call; the legacy staged path is
        # only a fallback for drivers that reject SetDisplayConfig.
        positions_changed = any(
            (int(self._monitors_by_name(name)["x"]),
             int(self._monitors_by_name(name)["y"])) != position
            for name, position in positions.items()
        )
        ok, message = True, "Display layout applied."
        if positions_changed:
            ok, ccd_message = self._apply_positions_via_ccd(positions)
            if ok:
                if ccd_message:
                    message = ccd_message
            else:
                ok, message = self._apply_staged_layout(wanted, positions)
        if not ok:
            self.refresh()
            return False, message

        # Resolution/refresh changes per monitor; failures are reported but do
        # not roll back the position/primary switch.
        mode_errors = []
        for mon in wanted:
            code = self._apply_mode(mon)
            if code is not None and code < 0:
                mode_errors.append("%s: %s" % (mon["name"], _win_error(code)))

        self.refresh()
        if mode_errors:
            message += " Could not change the mode of: %s." % "; ".join(mode_errors)
        if missing:
            message += " Skipped disconnected display(s): %s." % ", ".join(missing)
        return not mode_errors, message

    def _monitors_by_name(self, name):
        """The live monitor dict for ``name`` from the last snapshot, or None."""
        for mon in self._monitors:
            if mon["name"] == name:
                return mon
        return None

    def _layout_is_current(self, wanted, positions):
        """True when every monitor's position and mode already match ``wanted``.

        Launching a profile that captured the current layout is then a no-op:
        no driver call, no flicker, and no chance of a driver rejecting the
        staging of settings that are already in effect.
        """
        for mon in wanted:
            live = self._monitors_by_name(mon.get("name"))
            if live is None:
                continue  # disconnected; handled by the caller
            if (int(live.get("x", 0)), int(live.get("y", 0))) != positions[mon["name"]]:
                return False
            if (int(live.get("width", 0)) != int(mon.get("width", 0))
                    or int(live.get("height", 0)) != int(mon.get("height", 0))):
                return False
            refresh = int(mon.get("refresh_rate") or 0)
            if refresh and refresh != int(live.get("refresh_rate") or 0):
                return False
        return True

    def _apply_positions_via_ccd(self, positions):
        """Apply the layout's positions (and the primary) with SetDisplayConfig.

        Returns ``(success, message)``. In CCD the primary monitor is simply the
        one whose source-mode position is ``(0, 0)``; ``positions`` is already
        computed so the requested primary lands there.
        """
        u = self._user32
        path_count = wintypes.UINT()
        mode_count = wintypes.UINT()
        if u.GetDisplayConfigBufferSizes(
            QDC_ONLY_ACTIVE_PATHS, ctypes.byref(path_count), ctypes.byref(mode_count)
        ) != ERROR_SUCCESS:
            return False, _sdc_error(ERROR_INVALID_PARAMETER)

        paths = (DISPLAYCONFIG_PATH_INFO * path_count.value)()
        modes = (DISPLAYCONFIG_MODE_INFO * mode_count.value)()
        pc = wintypes.UINT(path_count.value)
        mc = wintypes.UINT(mode_count.value)
        if u.QueryDisplayConfig(
            QDC_ONLY_ACTIVE_PATHS, ctypes.byref(pc), paths,
            ctypes.byref(mc), modes, None,
        ) != ERROR_SUCCESS:
            return False, _sdc_error(ERROR_INVALID_PARAMETER)

        # Retarget each active source's position to the requested layout.
        touched = False
        for path in paths[:pc.value]:
            source = DISPLAYCONFIG_SOURCE_DEVICE_NAME()
            if not self._device_info(
                source, DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME,
                path.sourceInfo.adapterId, path.sourceInfo.id,
            ):
                continue
            device_name = source.viewGdiDeviceName
            if device_name not in positions:
                continue
            mode_index = path.sourceInfo.modeInfoIdx
            if mode_index >= len(modes):
                continue
            x, y = positions[device_name]
            modes[mode_index].u.sourceMode.position.x = x
            modes[mode_index].u.sourceMode.position.y = y
            touched = True

        if not touched:
            return False, _sdc_error(ERROR_INVALID_PARAMETER)

        base_flags = SDC_APPLY | SDC_USE_SUPPLIED_DISPLAY_CONFIG | SDC_ALLOW_CHANGES
        code = u.SetDisplayConfig(
            pc.value, paths, mc.value, modes, base_flags | SDC_SAVE_TO_DATABASE
        )
        if code != ERROR_SUCCESS:
            # Some drivers refuse to persist to the database; apply anyway.
            code = u.SetDisplayConfig(
                pc.value, paths, mc.value, modes, base_flags
            )
        if code != ERROR_SUCCESS:
            return False, _sdc_error(code)
        return True, None

    def _apply_staged_layout(self, wanted, positions):
        """Fallback: stage the whole layout with CDS_NORESET and commit once.

        Only used when SetDisplayConfig is unavailable.  Monitors whose staged
        settings already match the current ones are skipped (some drivers
        reject staging identical settings for the primary display).  If a stage
        is still rejected, the monitors staged so far are put back to their
        current values before committing, so a half-layout is never applied:
        committing with flags 0 *applies* pending staged changes, it does not
        discard them. Returns ``(success, message)``.
        """
        staged = []  # (device_name, original DEVMODE bytes)
        for mon in wanted:
            devmode = self._current_devmode(mon["name"])
            if devmode is None:
                self._undo_staged(staged)
                return False, "%s is not attached." % mon["name"]
            original = ctypes.string_at(
                ctypes.byref(devmode), ctypes.sizeof(DEVMODE)
            )
            code = self._stage_monitor(mon, positions[mon["name"]])
            if code is None:
                continue  # nothing differs for this monitor
            if code < 0:
                self._undo_staged(staged)
                return False, "%s: %s" % (mon["name"], _win_error(code))
            staged.append((mon["name"], original))

        code = self._user32.ChangeDisplaySettingsExW(None, None, None, 0, None)
        if code < 0:
            return False, _win_error(code)
        return True, None

    def _undo_staged(self, staged):
        """Commit the monitors' original devmodes to cancel a failed staging.

        Windows has no "discard pending staged changes" call, so the closest
        equivalent is to stage the original values back and commit them.
        """
        if not staged:
            return
        for name, original in staged:
            devmode = DEVMODE.from_buffer_copy(original)
            self._user32.ChangeDisplaySettingsExW(
                name, ctypes.byref(devmode), None,
                CDS_UPDATEREGISTRY | CDS_NORESET, None,
            )
        self._user32.ChangeDisplaySettingsExW(None, None, None, 0, None)

    def _apply_mode(self, mon):
        """Change a monitor's resolution/refresh only.

        Returns ``None`` when the mode already matches (nothing to do),
        otherwise the ChangeDisplaySettingsExW return code (0 on success).
        Falls back to SetDisplayConfig when the legacy call is rejected, which
        happens on HDR-enabled displays.
        """
        devmode = self._current_devmode(mon["name"])
        if devmode is None:
            return -1  # DISP_CHANGE_BADMODE

        width = int(mon.get("width", devmode.dmPelsWidth))
        height = int(mon.get("height", devmode.dmPelsHeight))
        refresh = int(mon.get("refresh_rate") or 0)

        if (width == int(devmode.dmPelsWidth)
                and height == int(devmode.dmPelsHeight)
                and (not refresh or refresh == int(devmode.dmDisplayFrequency))):
            return None

        devmode.dmPelsWidth = width
        devmode.dmPelsHeight = height
        devmode.dmFields = DM_PELSWIDTH | DM_PELSHEIGHT | DM_BITSPERPEL
        if refresh:
            devmode.dmDisplayFrequency = refresh
            devmode.dmFields |= DM_DISPLAYFREQUENCY

        code = self._user32.ChangeDisplaySettingsExW(
            mon["name"], ctypes.byref(devmode), None, CDS_UPDATEREGISTRY, None
        )
        if code >= 0:
            return code

        # HDR displays reject legacy mode changes; SetDisplayConfig is the API
        # Windows' own Display settings use and handles HDR fine.
        if self._apply_mode_via_ccd(mon["name"], width, height, refresh):
            return 0
        return code

    def _apply_mode_via_ccd(self, device_name, width, height, refresh):
        """Change one monitor's mode with SetDisplayConfig (HDR-safe).

        Only the fields that need to change are touched: the source
        width/height and the target refresh rate. Returns True on success.
        """
        u = self._user32
        path_count = wintypes.UINT()
        mode_count = wintypes.UINT()
        if u.GetDisplayConfigBufferSizes(
            QDC_ONLY_ACTIVE_PATHS, ctypes.byref(path_count), ctypes.byref(mode_count)
        ) != ERROR_SUCCESS:
            return False

        paths = (DISPLAYCONFIG_PATH_INFO * path_count.value)()
        modes = (DISPLAYCONFIG_MODE_INFO * mode_count.value)()
        pc = wintypes.UINT(path_count.value)
        mc = wintypes.UINT(mode_count.value)
        if u.QueryDisplayConfig(
            QDC_ONLY_ACTIVE_PATHS, ctypes.byref(pc), paths,
            ctypes.byref(mc), modes, None,
        ) != ERROR_SUCCESS:
            return False

        touched = False
        for path in paths[:pc.value]:
            source = DISPLAYCONFIG_SOURCE_DEVICE_NAME()
            if not self._device_info(
                source, DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME,
                path.sourceInfo.adapterId, path.sourceInfo.id,
            ):
                continue
            if source.viewGdiDeviceName != device_name:
                continue

            source_index = path.sourceInfo.modeInfoIdx
            if source_index >= len(modes):
                continue
            modes[source_index].u.sourceMode.width = width
            modes[source_index].u.sourceMode.height = height

            if refresh:
                # Update the refresh in both places SetDisplayConfig reads it.
                ratio = DISPLAYCONFIG_RATIONAL(refresh * 1000, 1000)
                path.targetInfo.refreshRate = ratio
                target_index = path.targetInfo.modeInfoIdx
                if target_index < len(modes):
                    modes[target_index].u.targetMode.targetVideoSignalInfo.vSyncFreq = ratio
            touched = True

        if not touched:
            return False

        base_flags = SDC_APPLY | SDC_USE_SUPPLIED_DISPLAY_CONFIG | SDC_ALLOW_CHANGES
        code = u.SetDisplayConfig(
            pc.value, paths, mc.value, modes, base_flags | SDC_SAVE_TO_DATABASE
        )
        if code != ERROR_SUCCESS:
            # Some drivers refuse to persist to the database; apply anyway.
            code = u.SetDisplayConfig(pc.value, paths, mc.value, modes, base_flags)
        return code == ERROR_SUCCESS

    def _stage_monitor(self, mon, position):
        """Stage one monitor's mode + position with CDS_NORESET.

        Returns ``None`` when the monitor already matches (nothing staged),
        otherwise the ChangeDisplaySettingsExW return code.
        """
        devmode = self._current_devmode(mon["name"])
        if devmode is None:
            return -1

        position_x, position_y = position
        width = int(mon.get("width", devmode.dmPelsWidth))
        height = int(mon.get("height", devmode.dmPelsHeight))
        refresh_rate = int(mon.get("refresh_rate") or 0)

        unchanged = (
            int(devmode.dmPosition.x) == position_x
            and int(devmode.dmPosition.y) == position_y
            and int(devmode.dmPelsWidth) == width
            and int(devmode.dmPelsHeight) == height
            and (not refresh_rate
                 or int(devmode.dmDisplayFrequency) == refresh_rate)
        )
        if unchanged:
            return None

        devmode.dmPosition.x, devmode.dmPosition.y = position
        devmode.dmPelsWidth = width
        devmode.dmPelsHeight = height
        devmode.dmFields = DM_POSITION | DM_PELSWIDTH | DM_PELSHEIGHT | DM_BITSPERPEL
        if refresh_rate:
            devmode.dmDisplayFrequency = refresh_rate
            devmode.dmFields |= DM_DISPLAYFREQUENCY

        return self._user32.ChangeDisplaySettingsExW(
            mon["name"], ctypes.byref(devmode), None,
            CDS_UPDATEREGISTRY | CDS_NORESET, None
        )

    # ---------- profile helpers ----------
    def capture_layout(self):
        """Snapshot the current layout in the profile JSON schema."""
        monitors = self.refresh()
        primary = next((m for m in monitors if m["is_primary"]), None)
        return {
            "primary": primary["name"] if primary else None,
            "monitors": [
                {
                    "id": m["id"],
                    "name": m["name"],
                    "label": m["label"],
                    "width": m["width"],
                    "height": m["height"],
                    "x": m["x"],
                    "y": m["y"],
                    "refresh_rate": m["refresh_rate"],
                    "hdr_enabled": m["hdr_enabled"],
                    "is_primary": m["is_primary"],
                }
                for m in monitors
            ],
        }

    def apply_display_config(self, display_config):
        """Apply the ``display`` block of a profile. Returns ``(success, message)``."""
        if not display_config:
            return True, "Profile has no display settings; left unchanged."

        monitors = [dict(m) for m in display_config.get("monitors", [])]
        primary_name = display_config.get("primary")
        if primary_name:
            for mon in monitors:
                mon["is_primary"] = mon.get("name") == primary_name

        success, message = self.apply_layout(monitors)

        # HDR is applied after the layout: switching resolution or primary can
        # reset the colour state, so setting it first would be undone.
        hdr_notes = []
        for mon in monitors:
            wanted = mon.get("hdr_enabled")
            if wanted is None:
                continue  # profile predates HDR support; leave it alone
            current = self.get_monitor(mon.get("name"))
            if current is None or not current.get("hdr_supported"):
                continue
            if bool(current.get("hdr_enabled")) == bool(wanted):
                continue

            hdr_ok, hdr_message = self.set_hdr(mon["name"], bool(wanted))
            if not hdr_ok:
                hdr_notes.append(hdr_message)

        if hdr_notes:
            message += " " + " ".join(hdr_notes)
        return success, message
