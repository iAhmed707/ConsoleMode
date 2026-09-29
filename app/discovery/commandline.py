"""Windows command-line tokenising and executable/argument parsing.

Uninstall strings arrive as raw command lines such as::

    "C:\\Program Files\\App\\AppUninstall.exe" /uninstall /quiet
    msiexec.exe /x {GUID} /qn
    C:\\Apps\\thing with space\\setup.exe /S

Naively splitting on whitespace would break every path that contains a space.
This module tokenises a command line using the same backslash/quote rules the
Windows C runtime uses (the rules behind ``CommandLineToArgvW``), so the
executable can be separated from its arguments without guessing.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

_WHITESPACE = " \t"


def tokenize_command_line(line: str) -> List[str]:
    """Split a Windows command line into arguments, CommandLineToArgvW-style.

    The quoting rules implemented here are the documented ones:

    * Whitespace separates arguments.
    * A run of ``n`` backslashes followed by a quote yields ``n // 2``
      backslashes; if ``n`` is odd the quote is a literal quote, if even the
      quote toggles the in-quotes state.
    * A quote outside quotes toggles quoting on/off; two adjacent quotes inside
      quotes produce one literal quote.
    """
    if line is None:
        return []

    args: List[str] = []
    current: List[str] = []
    in_quotes = False
    i = 0
    n = len(line)

    while i < n:
        ch = line[i]

        if in_quotes:
            if ch == "\\":
                backslashes = 0
                while i < n and line[i] == "\\":
                    backslashes += 1
                    i += 1
                if i < n and line[i] == '"':
                    current.extend("\\" * (backslashes // 2))
                    if backslashes % 2 == 1:
                        current.append('"')      # escaped literal quote
                    else:
                        in_quotes = False        # closing quote
                    i += 1
                else:
                    current.extend("\\" * backslashes)
            elif ch == '"':
                # Two adjacent quotes inside quotes -> one literal quote.
                if i + 1 < n and line[i + 1] == '"':
                    current.append('"')
                    i += 2
                else:
                    in_quotes = False
                    i += 1
            else:
                current.append(ch)
                i += 1
            continue

        # Not in quotes.
        if ch in _WHITESPACE:
            if current:
                args.append("".join(current))
                current = []
            i += 1
        elif ch == "\\":
            backslashes = 0
            while i < n and line[i] == "\\":
                backslashes += 1
                i += 1
            if i < n and line[i] == '"':
                current.extend("\\" * (backslashes // 2))
                if backslashes % 2 == 1:
                    current.append('"')
                else:
                    in_quotes = True
                i += 1
            else:
                current.extend("\\" * backslashes)
        elif ch == '"':
            in_quotes = True
            i += 1
        else:
            current.append(ch)
            i += 1

    if current:
        args.append("".join(current))
    return args


def split_executable(line: str) -> Tuple[str, str]:
    """Return ``(executable, arguments)`` for a command line.

    The executable is the first token; ``arguments`` is the remainder of the
    original string (preserved verbatim).  Both are stripped of whitespace and
    surrounding quotes.
    """
    if not line or not line.strip():
        return "", ""

    stripped = line.strip()
    tokens = tokenize_command_line(stripped)
    if not tokens:
        return "", ""

    exe = _strip_quotes(tokens[0])

    # Recover the argument tail from the original text so it stays byte-exact
    # (tokenisation is lossy for repeated spaces).
    if len(tokens) == 1:
        return exe, ""
    idx = stripped.find(tokens[1])
    if idx == -1:
        args = stripped[len(tokens[0]):].strip()
    else:
        args = stripped[idx:].strip()
    return exe, args


def _strip_quotes(text: str) -> str:
    text = (text or "").strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1]
    return text


def unquote(text: str) -> str:
    """Remove one pair of surrounding double quotes, if present."""
    return _strip_quotes(text)


def strip_icon_index(value: str) -> str:
    """Turn ``"C:\\App\\app.exe",0`` into ``C:\\App\\app.exe``.

    A DisplayIcon value commonly ends in ``",N"`` (icon resource index); the
    index is irrelevant when we only want the executable path.
    """
    if not value:
        return ""
    raw = str(value).strip()
    raw = unquote(raw)
    if "," in raw:
        raw = raw.rsplit(",", 1)[0].strip()
    return unquote(raw)
