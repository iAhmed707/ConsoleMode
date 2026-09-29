"""Lightweight Windows integration tests for the fast scanners.

These only exercise the cheap, read-only scanners (registry + MSI) so the test
suite stays quick; the PowerShell-backed scanners are covered by the live app
rather than the unit suite.
"""

import sys
import unittest

from app.discovery.scanners import MsiScanner, RegistryScanner


@unittest.skipUnless(sys.platform == "win32", "requires Windows")
class ScannerTests(unittest.TestCase):
    def test_registry_scanner_readonly_and_populated(self):
        items = RegistryScanner().scan()
        self.assertTrue(items, "expected some registry uninstall entries")
        names = {i.name for i in items}
        self.assertTrue(names)
        # Every item is read-only metadata (no side effects asserted here, but
        # the scanner only ever opens keys with KEY_READ).
        for item in items:
            self.assertTrue(item.name)
            self.assertIn(item.source, ("Registry",))

    def test_msi_scanner_readonly(self):
        items = MsiScanner().scan()
        # A bare Windows box has many MSI products; assert the shape rather
        # than a hard count.
        for item in items:
            self.assertTrue(item.product_code)
            self.assertEqual(item.installer_type, "msi")


if __name__ == "__main__":
    unittest.main()
