"""Drag launched application windows onto the primary display.

Some applications (Playnite among them) reopen on the monitor they were last
closed on, ignoring which display is currently primary.  A profile launch can
therefore apply its display layout correctly and the app still open on the
wrong screen.  This module watches for a freshly launched process' top-level
windows and, during their first moments, moves any that are not already on the
primary display into the primary's work area.

Everything goes through ``ctypes`` so the rest of the app stays
dependency-free and Qt-free; the polling loop is expected to run on a worker
thread.
"""

import ctypes
import sys
import time
from ctypes import wintypes

IS_WINDOWS = sys.platform == "win32"

# SetWindowPos flags: keep the z-order and do not steal focus.
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010

MONITOR_DEFAULTTOPRIMARY = 0x00000001

# DwmGetWindowAttribute attribute ids
DWMWA_CLOAKED = 14


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
    ]


_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

_user32 = None
_dwmapi = None

if IS_WINDOWS:
    _user32 = ctypes.windll.user32
    _dwmapi = ctypes.windll.dwmapi

    _user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
    _user32.EnumWindows.restype = wintypes.BOOL

    _user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND, ctypes.POINTER(wintypes.DWORD)
    ]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD

    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.IsWindowVisible.restype = wintypes.BOOL

    _user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    _user32.GetWindowRect.restype = wintypes.BOOL

    _user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, wintypes.UINT,
    ]
    _user32.SetWindowPos.restype = wintypes.BOOL

    _user32.MonitorFromPoint.argtypes = [POINT, wintypes.DWORD]
    _user32.MonitorFromPoint.restype = wintypes.HMONITOR

    _user32.GetMonitorInfoW.argtypes = [
        wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)
    ]
    _user32.GetMonitorInfoW.restype = wintypes.BOOL

    _dwmapi.DwmGetWindowAttribute.argtypes = [
        wintypes.HWND, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD
    ]
    _dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long


# ---------- pure geometry helpers (unit-tested) ----------
def center_rect(left, top, width, height, work):
    """Place a ``width x height`` window centered inside a work area.

    ``work`` is ``(left, top, width, height)``.  Windows larger than the work
    area are shrunk to fit it.  Returns ``(x, y, width, height)``.
    """
    work_left, work_top, work_width, work_height = work
    width = min(max(int(width), 1), int(work_width))
    height = min(max(int(height), 1), int(work_height))
    x = int(work_left) + (int(work_width) - width) // 2
    y = int(work_top) + (int(work_height) - height) // 2
    return x, y, width, height


def is_on_primary(rect, work):
    """True when the rectangle's center lies inside the primary work area.

    ``rect`` is ``(left, top, right, bottom)`` and ``work`` is
    ``(left, top, width, height)``.
    """
    left, top, right, bottom = rect
    work_left, work_top, work_width, work_height = work
    center_x = (left + right) / 2.0
    center_y = (top + bottom) / 2.0
    return (work_left <= center_x <= work_left + work_width
            and work_top <= center_y <= work_top + work_height)


# ---------- Win32 wrappers ----------
def primary_work_area():
    """The primary monitor's work area as ``(left, top, width, height)``.

    Physical pixels, so the values can be handed straight to SetWindowPos.
    """
    if _user32 is None:
        return (0, 0, 0, 0)

    monitor = _user32.MonitorFromPoint(POINT(0, 0), MONITOR_DEFAULTTOPRIMARY)
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if not _user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return (0, 0, 0, 0)
    return (info.rcWork.left, info.rcWork.top,
            info.rcWork.right - info.rcWork.left,
            info.rcWork.bottom - info.rcWork.top)


def _is_cloaked(hwnd):
    """True when DWM reports the window as cloaked (e.g. a splash overlay)."""
    if _dwmapi is None:
        return False
    value = wintypes.DWORD()
    result = _dwmapi.DwmGetWindowAttribute(
        hwnd, DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value)
    )
    return result == 0 and value.value != 0


def find_process_windows(pid):
    """Top-level, visible, uncloaked window handles owned by ``pid``."""
    if _user32 is None:
        return []

    windows = []

    @_WNDENUMPROC
    def callback(hwnd, lparam):
        window_pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
        if window_pid.value == pid and _user32.IsWindowVisible(hwnd):
            if not _is_cloaked(hwnd):
                windows.append(hwnd)
        return True

    _user32.EnumWindows(callback, 0)
    return windows


def move_window_to_primary(hwnd):
    """Center one window on the primary monitor's work area.

    Windows whose center is already on the primary are left untouched, so an
    app that opened in the right place keeps its own position.  Returns True
    when the window was moved.
    """
    if _user32 is None:
        return False

    rect = RECT()
    if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return False

    work = primary_work_area()
    if work[2] <= 0 or work[3] <= 0:
        return False

    if is_on_primary((rect.left, rect.top, rect.right, rect.bottom), work):
        return False

    x, y, width, height = center_rect(rect.left, rect.top, width, height, work)
    return bool(_user32.SetWindowPos(
        hwnd, None, x, y, width, height, SWP_NOZORDER | SWP_NOACTIVATE
    ))


def move_process_to_primary(pid, timeout=10.0, interval=0.5, nudge_seconds=2.5):
    """Poll for ``pid``'s windows and keep them on the primary display.

    Each window is only corrected during its first ``nudge_seconds`` of life,
    so a user who grabs the window right away is never fought afterwards, and
    a window that already opened on the primary is never repositioned.  Runs
    synchronously; call from a worker thread.
    """
    if _user32 is None:
        return

    deadline = time.monotonic() + timeout
    seen = {}  # hwnd -> first-seen monotonic timestamp
    while time.monotonic() < deadline:
        for hwnd in find_process_windows(pid):
            now = time.monotonic()
            first_seen = seen.get(hwnd)
            if first_seen is None:
                seen[hwnd] = now
                move_window_to_primary(hwnd)
            elif now - first_seen < nudge_seconds:
                move_window_to_primary(hwnd)
        time.sleep(interval)
