"""Authenticode digital-signature inspection.

Signature state is checked with the Windows Authenticode API — the same
``WinVerifyTrust`` machinery the operating system uses — surfaced through the
``Get-AuthenticodeSignature`` cmdlet in a single batched PowerShell call (one
process for *all* files, never one per file).  The certificate subject/issuer
are read from the embedded signing certificate.

A missing signature is **not** treated as malicious: many legitimate small and
open-source tools are unsigned.  The signature is only used to raise
confidence in an application's identity.
"""

from __future__ import annotations

import json
from typing import Dict, Iterable, List

from ..powershell import run_json
from .base import BaseScanner

_QUERY_TEMPLATE = r"""
$ErrorActionPreference = 'SilentlyContinue'
$paths = '{paths_json}' | ConvertFrom-Json
$out = foreach ($p in $paths) {
    $s = Get-AuthenticodeSignature -LiteralPath $p -ErrorAction SilentlyContinue
    [pscustomobject]@{
        Path = [string]$p
        Status = [string]$s.Status
        Subject = if ($s.SignerCertificate) { [string]$s.SignerCertificate.Subject } else { $null }
        Issuer = if ($s.SignerCertificate) { [string]$s.SignerCertificate.Issuer } else { $null }
    }
}
$out | ConvertTo-Json -Depth 3 -Compress
"""


class SignatureScanner(BaseScanner):
    name = "Signature"

    def scan(self, paths: Iterable[str]) -> Dict[str, dict]:
        """Return ``{path: {status, subject, issuer, is_signed}}``."""
        targets = [p for p in paths if p and not p.lower().startswith("shell:")]
        if not targets:
            return {}

        # JSON is embedded in a single-quoted PowerShell string; only single
        # quotes need doubling (double quotes are fine).  ``.replace`` is used
        # instead of ``str.format`` because the template contains ``{...}``
        # hashtable literals.
        paths_json = json.dumps(targets).replace("'", "''")
        script = _QUERY_TEMPLATE.replace("{paths_json}", paths_json)
        result = run_json(script, timeout=60.0)
        if result is None:
            return {}
        if isinstance(result, dict):
            result = [result]

        output: Dict[str, dict] = {}
        for entry in result:
            if not isinstance(entry, dict):
                continue
            status = (entry.get("Status") or "").strip()
            output[entry.get("Path") or ""] = {
                "status": status,
                "subject": (entry.get("Subject") or "").strip(),
                "issuer": (entry.get("Issuer") or "").strip(),
                "is_signed": status.lower() == "valid",
            }
        return output
