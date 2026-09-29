"""Tests for the window-placement geometry helpers.

Only the pure math is tested here; the Win32 calls are exercised by the live
probe (window_move_test.py) on a real Windows desktop.
"""

import unittest

from app.managers.window_manager import center_rect, is_on_primary

WORK = (0, 0, 1920, 1040)  # typical primary work area


class CenterRectTests(unittest.TestCase):
    def test_smaller_window_is_centered_and_kept(self):
        self.assertEqual(center_rect(0, 0, 400, 300, WORK), (760, 370, 400, 300))

    def test_oversized_window_is_shrunk_to_fit(self):
        x, y, w, h = center_rect(0, 0, 2560, 1440, WORK)
        self.assertEqual((w, h), (1920, 1040))
        self.assertEqual((x, y), (0, 0))

    def test_centering_rounds_down_odd_remainders(self):
        # (1920 - 401) // 2 == 759
        self.assertEqual(center_rect(0, 0, 401, 301, WORK), (759, 369, 401, 301))

    def test_work_area_offset_is_respected(self):
        work = (-2560, 100, 1920, 1000)
        self.assertEqual(center_rect(0, 0, 400, 300, work),
                         (-2560 + (1920 - 400) // 2, 100 + (1000 - 300) // 2,
                          400, 300))


class IsOnPrimaryTests(unittest.TestCase):
    def test_center_inside_is_on_primary(self):
        self.assertTrue(is_on_primary((100, 100, 500, 400), WORK))

    def test_center_outside_is_off_primary(self):
        self.assertFalse(is_on_primary((2000, 100, 2400, 400), WORK))
        self.assertFalse(is_on_primary((-2000, 100, -1600, 400), WORK))

    def test_window_on_secondary_to_the_left(self):
        self.assertFalse(is_on_primary((-1900, 100, -1500, 400), WORK))


if __name__ == "__main__":
    unittest.main()
