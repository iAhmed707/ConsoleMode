import os
import sys
import unittest

from app.discovery import pe
from app.discovery.models import machine_to_arch, ARCH_UNKNOWN, ARCH_X64, ARCH_X86


class MachineArchTests(unittest.TestCase):
    def test_known_machines(self):
        self.assertEqual(machine_to_arch(0x8664), ARCH_X64)
        self.assertEqual(machine_to_arch(0x014C), ARCH_X86)
        self.assertEqual(machine_to_arch(0xAA64), "arm64")

    def test_unknown_machine(self):
        self.assertEqual(machine_to_arch(0xDEAD), ARCH_UNKNOWN)


@unittest.skipUnless(sys.platform == "win32", "requires Windows")
class PeTests(unittest.TestCase):
    def test_python_exe_architecture(self):
        arch = pe.read_architecture(sys.executable)
        self.assertIn(arch, ("x64", "x86", "arm64", "arm"))

    def test_non_pe_returns_unknown(self):
        with open("tests/_not_a_pe.txt", "w", encoding="utf-8") as handle:
            handle.write("hello world")
        try:
            self.assertEqual(pe.read_architecture("tests/_not_a_pe.txt"), ARCH_UNKNOWN)
        finally:
            os.unlink("tests/_not_a_pe.txt")

    def test_version_info_has_company(self):
        # A real, signed system binary has version info.
        notepad = os.path.join(os.environ.get("WINDIR", r"C:\Windows"),
                               "System32", "notepad.exe")
        info = pe.read_version_info(notepad)
        self.assertIn("CompanyName", info)
        self.assertEqual(info["CompanyName"], "Microsoft Corporation")


if __name__ == "__main__":
    unittest.main()
