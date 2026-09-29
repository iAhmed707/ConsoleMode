"""Live check of the window mover: opens a probe window, parks it off the
primary display, and verifies move_window_to_primary drags it back.

Safe: only a small PySide6 probe window is shown and then closed.
"""

import ctypes
import subprocess
import sys
import time

from app.managers.window_manager import (
    RECT,
    find_process_windows,
    move_window_to_primary,
    primary_work_area,
)

CHILD_CODE = (
    "import sys;"
    "from PySide6.QtWidgets import QApplication, QLabel;"
    "app = QApplication(sys.argv);"
    "w = QLabel('ConsoleMode window probe');"
    "w.setWindowTitle('consolemode-window-probe');"
    "w.resize(420, 300);"
    "w.show();"
    "sys.exit(app.exec())"
)


def get_rect(hwnd):
    rect = RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return (rect.left, rect.top, rect.right, rect.bottom)


def main():
    user32 = ctypes.windll.user32
    user32.SetWindowPos.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.c_uint,
    ]
    user32.SetWindowPos.restype = ctypes.c_int

    process = subprocess.Popen([sys.executable, "-c", CHILD_CODE])
    try:
        hwnd = None
        for _ in range(40):
            hwnds = find_process_windows(process.pid)
            if hwnds:
                hwnd = hwnds[0]
                break
            time.sleep(0.25)

        if hwnd is None:
            print("FAIL: no window found for pid", process.pid)
            return 1

        work = primary_work_area()
        print("primary work area:", work)

        # Park the probe far off the primary (the FHD sits at x=-1920 here).
        user32.SetWindowPos(hwnd, None, -1800, 100, 420, 300, 0x0004 | 0x0010)
        time.sleep(0.3)
        print("parked off-primary at:", get_rect(hwnd))

        moved = move_window_to_primary(hwnd)
        time.sleep(0.3)
        after = get_rect(hwnd)
        print("move_window_to_primary ->", moved, "| now at:", after)

        center_x = (after[0] + after[2]) / 2.0
        center_y = (after[1] + after[3]) / 2.0
        on_primary = (work[0] <= center_x <= work[0] + work[2]
                      and work[1] <= center_y <= work[1] + work[3])
        print("window center on primary:", on_primary)

        # A window that is already on the primary must not be touched again.
        again = move_window_to_primary(hwnd)
        print("second call leaves it alone:", not again)

        ok = moved and on_primary and not again
        print("OK" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        process.terminate()


if __name__ == "__main__":
    sys.exit(main())
