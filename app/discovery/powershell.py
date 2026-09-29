"""Small helper for invoking PowerShell read-only queries.

PowerShell is used only as a *fallback* where a Win32 API is not practical to
drive from ``ctypes`` (AppX/MSIX via the ``PackageManager`` WinRT surface,
WMI ``Win32_Service``, ``Get-ScheduledTask``, and Authenticode verification —
the latter is ``WinVerifyTrust`` under the hood).  Every invocation is a read
query; no script ever deletes a registry key, stops a service or runs an
uninstaller.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from typing import Any, Dict, List, Optional

_PS_EXE = os.environ.get("SystemRoot", r"C:\Windows") + r"\System32\WindowsPowerShell\v1.0\powershell.exe"


def run_script(script: str, timeout: float = 30.0) -> Dict[str, Any]:
    """Write ``script`` to a temp ``.ps1`` and execute it read-only.

    Returns ``{"ok": bool, "stdout": str, "stderr": str, "code": int}``.
    Writing a temp file (rather than embedding the script in ``-Command``)
    sidesteps all shell quoting problems with paths and GUIDs.
    """
    if not os.path.isfile(_PS_EXE):
        return {"ok": False, "stdout": "", "stderr": "powershell.exe not found", "code": -1}

    tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False,
                                         encoding="utf-8-sig") as handle:
            handle.write(script)
            tmp = handle.name

        cmd = [
            _PS_EXE,
            "-NoLogo", "-NoProfile", "-NonInteractive",
            "-ExecutionPolicy", "Bypass",
            "-File", tmp,
        ]
        proc = subprocess.run(
            cmd, capture_output=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return {
            "ok": proc.returncode == 0,
            "stdout": (proc.stdout or b"").decode("utf-8", errors="replace"),
            "stderr": (proc.stderr or b"").decode("utf-8", errors="replace"),
            "code": proc.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": "PowerShell timed out", "code": -2}
    except OSError as error:
        return {"ok": False, "stdout": "", "stderr": str(error), "code": -3}
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def run_json(script: str, timeout: float = 30.0) -> Optional[Any]:
    """Run a script whose *last* output line is JSON and parse it.

    Returns ``None`` on any failure, so callers degrade gracefully (a scanner
    failing is never fatal to the whole discovery).
    """
    result = run_script(script, timeout)
    if not result["ok"]:
        return None
    text = result["stdout"].strip()
    if not text:
        return None

    # PowerShell may print warnings/progress before the JSON; parse the last
    # non-empty line that looks like JSON.
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except ValueError:
            continue
    return None


def as_list(value: Any) -> List[Any]:
    """Coerce a JSON value that may be an object, array, or ``None`` to a list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]
