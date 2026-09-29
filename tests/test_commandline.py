import unittest

from app.discovery.commandline import (
    split_executable,
    strip_icon_index,
    tokenize_command_line,
    unquote,
)


class TokenizeTests(unittest.TestCase):
    def test_simple_args(self):
        self.assertEqual(tokenize_command_line("a.exe /x /y"), ["a.exe", "/x", "/y"])

    def test_quoted_path_with_spaces(self):
        self.assertEqual(
            tokenize_command_line('"C:\\Program Files\\App\\uninstall.exe" /S'),
            ["C:\\Program Files\\App\\uninstall.exe", "/S"],
        )

    def test_embedded_quotes(self):
        self.assertEqual(tokenize_command_line('"a b" c'), ["a b", "c"])

    def test_backslash_before_quote(self):
        # Windows rule: odd backslashes before a quote escape it.
        self.assertEqual(tokenize_command_line(r'"C:\App\" x'), [r'C:\App" x'])

    def test_empty(self):
        self.assertEqual(tokenize_command_line(""), [])
        self.assertEqual(tokenize_command_line("   "), [])


class SplitExecutableTests(unittest.TestCase):
    def test_quoted_exe(self):
        exe, args = split_executable('"C:\\Program Files\\App\\AppUninstall.exe" /uninstall')
        self.assertEqual(exe, "C:\\Program Files\\App\\AppUninstall.exe")
        self.assertEqual(args, "/uninstall")

    def test_msiexec(self):
        exe, args = split_executable("MsiExec.exe /X{1234-5678} /qn")
        self.assertEqual(exe, "MsiExec.exe")
        self.assertIn("/X{1234-5678}", args)

    def test_no_args(self):
        exe, args = split_executable('"C:\\App\\setup.exe"')
        self.assertEqual(exe, "C:\\App\\setup.exe")
        self.assertEqual(args, "")

    def test_plain_path(self):
        exe, _ = split_executable("C:\\Apps\\thing.exe /S")
        self.assertEqual(exe, "C:\\Apps\\thing.exe")


class IconIndexTests(unittest.TestCase):
    def test_strip_index(self):
        self.assertEqual(strip_icon_index('"C:\\App\\app.exe",0'), "C:\\App\\app.exe")

    def test_negative_index(self):
        self.assertEqual(strip_icon_index('"C:\\App\\app.exe",-101'), "C:\\App\\app.exe")

    def test_no_index(self):
        self.assertEqual(strip_icon_index('"C:\\App\\app.exe"'), "C:\\App\\app.exe")

    def test_unquote(self):
        self.assertEqual(unquote('"hello"'), "hello")
        self.assertEqual(unquote("hello"), "hello")


if __name__ == "__main__":
    unittest.main()
