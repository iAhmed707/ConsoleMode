"""Tests for the display layout decision logic.

These never touch the real Windows display APIs: DisplayManager is created
without calling __init__ (no windll prototyping) and every driver call is
replaced by a recorder.
"""

import ctypes
import unittest

from app.managers.display_manager import (
    CDS_NORESET,
    CDS_UPDATEREGISTRY,
    DEVMODE,
    DisplayManager,
)

FHD = "\\\\.\\DISPLAY2"  # 1920x1080
K2 = "\\\\.\\DISPLAY1"   # 2560x1440


def _monitor(name, x, y, width, height, refresh, is_primary):
    return {
        "id": int(name.rsplit("DISPLAY", 1)[1]),
        "name": name,
        "label": name,
        "width": width,
        "height": height,
        "x": x,
        "y": y,
        "refresh_rate": refresh,
        "hdr_enabled": False,
        "is_primary": is_primary,
    }


class ApplyLayoutTests(unittest.TestCase):
    def make_manager(self, live):
        dm = DisplayManager.__new__(DisplayManager)
        dm._user32 = object()  # truthy -> the Windows code path is taken
        dm._monitors = [dict(m) for m in live]
        dm.refresh = lambda: dm._monitors

        calls = {"ccd": [], "staged": [], "modes": []}

        def ccd(positions):
            calls["ccd"].append(dict(positions))
            return True, None

        def staged(wanted, positions):
            calls["staged"].append(dict(positions))
            return True, None

        def mode(mon):
            calls["modes"].append(mon["name"])
            return None

        dm._apply_positions_via_ccd = ccd
        dm._apply_staged_layout = staged
        dm._apply_mode = mode
        return dm, calls

    def test_identical_layout_is_a_noop(self):
        live = [
            _monitor(K2, 1920, 0, 2560, 1440, 240, False),
            _monitor(FHD, 0, 0, 1920, 1080, 180, True),
        ]
        profile = [dict(m) for m in live]
        dm, calls = self.make_manager(live)

        ok, message = dm.apply_layout(profile)

        self.assertTrue(ok)
        self.assertEqual(message, "Display layout already matches the profile.")
        self.assertEqual(calls["ccd"], [])
        self.assertEqual(calls["staged"], [])
        self.assertEqual(calls["modes"], [])

    def test_position_change_uses_ccd(self):
        live = [
            _monitor(K2, 0, 0, 2560, 1440, 240, True),
            _monitor(FHD, -1920, 0, 1920, 1080, 180, False),
        ]
        # The profile was captured while the FHD was primary, so the 2K sits
        # to its right.
        profile = [
            _monitor(K2, 1920, 0, 2560, 1440, 240, False),
            _monitor(FHD, 0, 0, 1920, 1080, 180, True),
        ]
        dm, calls = self.make_manager(live)

        ok, message = dm.apply_layout(profile)

        self.assertTrue(ok)
        self.assertEqual(message, "Display layout applied.")
        self.assertEqual(calls["ccd"], [{FHD: (0, 0), K2: (1920, 0)}])
        self.assertEqual(calls["staged"], [])
        self.assertEqual(calls["modes"], [K2, FHD])

    def test_ccd_failure_falls_back_to_staged(self):
        live = [
            _monitor(K2, 0, 0, 2560, 1440, 240, True),
            _monitor(FHD, -1920, 0, 1920, 1080, 180, False),
        ]
        profile = [
            _monitor(K2, 1920, 0, 2560, 1440, 240, False),
            _monitor(FHD, 0, 0, 1920, 1080, 180, True),
        ]
        dm, calls = self.make_manager(live)

        def ccd_fails(positions):
            calls["ccd"].append(dict(positions))
            return False, "Windows rejected the display topology."

        dm._apply_positions_via_ccd = ccd_fails

        ok, message = dm.apply_layout(profile)

        self.assertTrue(ok)
        self.assertEqual(calls["staged"], [{FHD: (0, 0), K2: (1920, 0)}])

    def test_mode_failure_does_not_undo_the_switch(self):
        live = [
            _monitor(K2, 0, 0, 2560, 1440, 60, True),
            _monitor(FHD, -1920, 0, 1920, 1080, 180, False),
        ]
        profile = [
            _monitor(K2, 1920, 0, 2560, 1440, 240, False),
            _monitor(FHD, 0, 0, 1920, 1080, 180, True),
        ]
        dm, calls = self.make_manager(live)

        def mode_fails(mon):
            calls["modes"].append(mon["name"])
            return -1  # driver rejected the 240 Hz mode change

        dm._apply_mode = mode_fails

        ok, message = dm.apply_layout(profile)

        # The position/primary switch went through; the mode rejection is
        # reported instead of silently leaving the wrong primary in place.
        self.assertEqual(calls["ccd"], [{FHD: (0, 0), K2: (1920, 0)}])
        self.assertFalse(ok)
        self.assertIn("Could not change the mode of", message)
        self.assertIn(K2, message)


class StageMonitorTests(unittest.TestCase):
    class FakeUser32:
        def __init__(self):
            self.staged = []

        def EnumDisplaySettingsW(self, device_name, index, devmode_ptr):
            devmode = ctypes.cast(devmode_ptr, ctypes.POINTER(DEVMODE)).contents
            devmode.dmPelsWidth = 2560
            devmode.dmPelsHeight = 1440
            devmode.dmDisplayFrequency = 240
            devmode.dmPosition.x = 0
            devmode.dmPosition.y = 0
            devmode.dmBitsPerPel = 32
            return True

        def ChangeDisplaySettingsExW(self, name, devmode_ptr, hwnd, flags, param):
            self.staged.append((name, flags))
            return 0

    def make_manager(self):
        dm = DisplayManager.__new__(DisplayManager)
        dm._user32 = StageMonitorTests.FakeUser32()
        return dm

    def test_unchanged_monitor_is_not_staged(self):
        dm = self.make_manager()
        mon = _monitor(K2, 0, 0, 2560, 1440, 240, True)

        code = dm._stage_monitor(mon, (0, 0))

        self.assertIsNone(code)
        self.assertEqual(dm._user32.staged, [])

    def test_changed_position_is_staged(self):
        dm = self.make_manager()
        mon = _monitor(K2, 1920, 0, 2560, 1440, 240, False)

        code = dm._stage_monitor(mon, (1920, 0))

        self.assertEqual(code, 0)
        self.assertEqual(
            dm._user32.staged,
            [(K2, CDS_UPDATEREGISTRY | CDS_NORESET)],
        )


if __name__ == "__main__":
    unittest.main()
