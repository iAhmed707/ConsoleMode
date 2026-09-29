import os
import shutil
import unittest

from app.managers.hotkey_manager import IS_WINDOWS, HotkeyManager
from app.managers.settings_manager import SettingsManager


class ParseSequenceTests(unittest.TestCase):
    def test_standard_combo(self):
        self.assertEqual(HotkeyManager.parse_sequence("Ctrl+Alt+L"), (0x3, 0x4C))

    def test_case_and_order_insensitive(self):
        self.assertEqual(
            HotkeyManager.parse_sequence("alt+CTRL+l"),
            HotkeyManager.parse_sequence("Ctrl+Alt+L"),
        )

    def test_meta_is_win(self):
        self.assertEqual(HotkeyManager.parse_sequence("Meta+Ctrl+Z"), (0x0A, 0x5A))

    def test_win_and_super_names(self):
        self.assertEqual(
            HotkeyManager.parse_sequence("Win+Z"),
            HotkeyManager.parse_sequence("Super+Z"),
        )

    def test_function_key(self):
        self.assertEqual(HotkeyManager.parse_sequence("F12"), (0, 0x7B))

    def test_single_key(self):
        self.assertEqual(HotkeyManager.parse_sequence("Z"), (0, 0x5A))

    def test_plus_key(self):
        self.assertEqual(HotkeyManager.parse_sequence("Ctrl++"), (0x2, 0xBB))
        # A trailing "+" is the plus key too ("Ctrl+" splits to Ctrl + empty).
        self.assertEqual(HotkeyManager.parse_sequence("Ctrl+"), (0x2, 0xBB))

    def test_minus_key(self):
        self.assertEqual(HotkeyManager.parse_sequence("Ctrl+-"), (0x2, 0xBD))

    def test_shift_equals(self):
        self.assertEqual(HotkeyManager.parse_sequence("Ctrl+Shift+="), (0x6, 0xBB))

    def test_named_keys(self):
        self.assertEqual(HotkeyManager.parse_sequence("Ctrl+Alt+Delete"), (0x3, 0x2E))
        self.assertEqual(HotkeyManager.parse_sequence("Ctrl+Shift+Escape"), (0x6, 0x1B))

    def test_two_non_modifier_keys_unsupported(self):
        self.assertIsNone(HotkeyManager.parse_sequence("Ctrl+A+B"))

    def test_modifiers_only_unsupported(self):
        self.assertIsNone(HotkeyManager.parse_sequence("Ctrl+Alt"))

    def test_empty_unsupported(self):
        self.assertIsNone(HotkeyManager.parse_sequence(""))
        self.assertIsNone(HotkeyManager.parse_sequence(None))
        self.assertIsNone(HotkeyManager.parse_sequence("   "))


class ConflictTests(unittest.TestCase):
    def setUp(self):
        self.manager = HotkeyManager()
        self.manager._registered = {
            "exit_console": (1, "Ctrl+Alt+X"),
            "show_window": (2, "Ctrl+Alt+G"),
        }

    def test_direct_conflict(self):
        self.assertEqual(
            self.manager.conflict_for("toggle_console", "Ctrl+Alt+X"),
            "exit_console",
        )

    def test_modifier_order_ignored(self):
        self.assertEqual(
            self.manager.conflict_for("toggle_console", "Alt+Ctrl+G"),
            "show_window",
        )

    def test_own_combo_ignored(self):
        self.assertIsNone(self.manager.conflict_for("exit_console", "Ctrl+Alt+X"))

    def test_no_conflict(self):
        self.assertIsNone(self.manager.conflict_for("toggle_console", "Ctrl+Alt+L"))

    def test_unsupported_text_ignored(self):
        self.assertIsNone(self.manager.conflict_for("toggle_console", "Ctrl+A+B"))


class StateTests(unittest.TestCase):
    def test_active(self):
        manager = HotkeyManager()
        manager._registered["toggle_console"] = (1, "Ctrl+Z")
        self.assertEqual(manager.state("toggle_console"), ("active", "Ctrl+Z"))

    def test_failed(self):
        manager = HotkeyManager()
        manager._last_failure["show_window"] = "Could not register Ctrl+Alt+G."
        self.assertEqual(
            manager.state("show_window"), ("failed", "Could not register Ctrl+Alt+G.")
        )

    def test_unassigned(self):
        manager = HotkeyManager()
        self.assertEqual(manager.state("toggle_console"), ("unassigned", ""))


@unittest.skipUnless(IS_WINDOWS, "RegisterHotKey is Windows-only")
class RegisterHotkeyTests(unittest.TestCase):
    COMBO = "Ctrl+Alt+Shift+F12"

    def setUp(self):
        self.manager = HotkeyManager()

    def tearDown(self):
        self.manager.unregister_all()

    def test_register_and_unregister(self):
        ok, message = self.manager.register_hotkey("toggle_console", self.COMBO)
        self.assertTrue(ok, message)
        self.assertEqual(self.manager.state("toggle_console")[0], "active")

        self.manager.unregister("toggle_console")
        self.assertEqual(self.manager.state("toggle_console")[0], "unassigned")

    def test_reapply_same_combo_is_a_noop(self):
        self.manager.register_hotkey("toggle_console", self.COMBO)
        ok, message = self.manager.register_hotkey("toggle_console", self.COMBO)
        self.assertTrue(ok, message)
        self.assertIn("Already active", message)
        self.assertEqual(len(self.manager.registered()), 1)

    def test_conflict_is_reported_before_windows(self):
        self.manager.register_hotkey("toggle_console", self.COMBO)
        ok, message = self.manager.register_hotkey("exit_console", self.COMBO)
        self.assertFalse(ok)
        self.assertIn("Launch / exit console mode", message)
        # The failed attempt must not have replaced the live binding.
        self.assertEqual(self.manager.registered()["toggle_console"], self.COMBO)


class SettingsHotkeyTests(unittest.TestCase):
    def setUp(self):
        # A unique dir inside the workspace (plain os.makedirs, not tempfile,
        # which sandboxed runs cannot write to or remove).
        workspace = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.tempdir = os.path.join(workspace, "test_settings_tmp_%d" % os.getpid())
        os.makedirs(self.tempdir, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(self.tempdir, ignore_errors=True))
        self.manager = SettingsManager(
            path=os.path.join(self.tempdir, "settings.json")
        )

    def test_defaults_when_unset(self):
        self.assertEqual(self.manager.hotkeys()["toggle_console"], "Ctrl+Alt+L")

    def test_custom_shortcut(self):
        self.manager.set_hotkey("toggle_console", "Ctrl+Shift+P")
        self.assertEqual(self.manager.hotkeys()["toggle_console"], "Ctrl+Shift+P")

    def test_cleared_shortcut_stays_cleared(self):
        ok, message = self.manager.set_hotkey("toggle_console", "")
        self.assertTrue(ok, message)
        self.assertEqual(self.manager.hotkeys()["toggle_console"], "")


if __name__ == "__main__":
    unittest.main()
