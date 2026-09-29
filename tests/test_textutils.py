import unittest

from app.discovery.textutils import (
    is_uninstaller_name,
    normalize_guid,
    normalize_name,
    normalize_path,
    normalize_version,
)


class GuidTests(unittest.TestCase):
    def test_normalise(self):
        self.assertEqual(
            normalize_guid("{CB7E1801-9FB8-4763-A369-1D7F290AB24D}"),
            "CB7E1801-9FB8-4763-A369-1D7F290AB24D",
        )
        self.assertEqual(normalize_guid("cb7e1801-9fb8-4763-a369-1d7f290ab24d"),
                         "CB7E1801-9FB8-4763-A369-1D7F290AB24D")

    def test_non_guid(self):
        self.assertEqual(normalize_guid("Not a GUID"), "")
        self.assertEqual(normalize_guid(""), "")


class NameTests(unittest.TestCase):
    def test_version_stripped(self):
        self.assertEqual(normalize_name("Google Chrome 120.0.6099"), "google chrome")

    def test_arch_suffix_stripped(self):
        self.assertEqual(normalize_name("7-Zip 23.01 (x64)"), "7 zip")

    def test_punctuation_collapsed(self):
        self.assertEqual(normalize_name("My App, Inc."), "my app inc")

    def test_case_insensitive(self):
        self.assertEqual(normalize_name("Visual Studio"), "visual studio")

    def test_empty(self):
        self.assertEqual(normalize_name(""), "")


class VersionTests(unittest.TestCase):
    def test_v_prefix(self):
        self.assertEqual(normalize_version("v1.2.3"), "1.2.3")

    def test_unchanged(self):
        self.assertEqual(normalize_version("1.2.3"), "1.2.3")

    def test_empty(self):
        self.assertEqual(normalize_version(""), "")


class PathTests(unittest.TestCase):
    def test_normalise(self):
        self.assertEqual(
            normalize_path("C:\\Program Files\\App\\"),
            "c:\\program files\\app",
        )

    def test_forward_slashes(self):
        self.assertEqual(normalize_path("C:/App/"), r"c:\app")


class UninstallerTests(unittest.TestCase):
    def test_uninstaller_names(self):
        self.assertTrue(is_uninstaller_name(r"C:\App\uninstall.exe"))
        self.assertTrue(is_uninstaller_name(r"C:\App\setup.exe"))
        self.assertTrue(is_uninstaller_name(r"C:\App\Unins000.exe"))

    def test_real_app_names(self):
        self.assertFalse(is_uninstaller_name(r"C:\App\App.exe"))
        self.assertFalse(is_uninstaller_name(r"C:\App\chrome.exe"))


if __name__ == "__main__":
    unittest.main()
