# Installed Programs Discovery Engine

A Revo Uninstaller-style discovery pipeline that enumerates Windows programs
from as many read-only sources as possible, normalises them, merges duplicates
and classifies the result.  It powers the **Add installed app…** picker.

The engine is **strictly read-only**: it never deletes a registry key or file,
never runs an uninstaller, never stops a service and never modifies a scheduled
task.

> This project is Python/PySide6, so the engine is Python.  Where the original
> design brief suggested C# `RegistryView.Registry64/Registry32`, the equivalent
> here is `winreg`'s `KEY_WOW64_64KEY` / `KEY_WOW64_32KEY` access flags.  Every
> Windows API below is still the official one, driven through `ctypes`,
> `winreg`, COM or a documented PowerShell wrapper.

---

## 1. Architecture

```
DiscoveryManager  (engine.py — parallel orchestration, timeout, cancellation, logging)
│
├─ RegistryScanner        winreg  (HKLM 64/32 views + HKCU)
├─ MsiScanner             msi.dll (MsiEnumProductsW / MsiGetProductInfoW)
├─ AppxScanner            Get-AppxPackage + Get-StartApps  (WinRT PackageManager wrapper)
├─ ServiceScanner         Win32_Service (WMI)
├─ StartupScanner         Run/RunOnce keys + Startup folders
├─ ScheduledTaskScanner   Get-ScheduledTask (Task Scheduler API wrapper)
├─ ShortcutScanner        WScript.Shell COM (.lnk resolution)
└─ PortableScanner        (optional) bounded folder walk + PE metadata

        │  each returns RawDiscoveryItem
        ▼
     Normalizer  (fill gaps, parse commands, resolve arch)
        ▼
  DeduplicationEngine  (scored matching → Application)
        ▼
   ClassificationEngine  (Normal / Update / Runtime / Driver / Framework / …)
        ▼
   launch-path resolver + FileMetadataScanner (PE) + SignatureScanner (Authenticode)
        ▼
     ApplicationDatabase  →  picker UI
```

**Discovery vs. Deep Scan.**  These are separate concerns and are kept separate:

* **Discovery** (this engine) answers *"what is installed?"* — it reads the
  registry / MSI / packages and produces one `Application` per program.
* **Deep Scan** answers *"for a specific program, what files/keys/services
  belong to it?"*  That is a per-program operation and is intentionally **not**
  implemented here; the `Application` model exposes the components needed to
  drive it later (install location, uninstall command, service/startup/task
  links) without performing it.

### Data model

* `RawDiscoveryItem` — one un-merged finding from a scanner (mirrors the
  registry value names: `DisplayName`, `UninstallString`, …).
* `Component` — a related artifact (service / startup / scheduled task /
  shortcut / executable).
* `Application` — the merged, classified result shown in the UI, with
  `sources`, `components`, `confidence`, `classification`, `signature`.
* `DiscoveryResult` — apps + logs + errors + per-scanner counts.

---

## 2. Windows APIs used (and why)

| Scanner | API | Why this one |
|---|---|---|
| Registry | `winreg.OpenKey(..., KEY_READ \| KEY_WOW64_64KEY/32KEY)` | Reads the 64-bit and 32-bit registry views with one API; the 32-bit view maps transparently to `WOW6432Node`. `KEY_READ` only — no write access. |
| MSI | `msi.dll` `MsiEnumProductsW` + `MsiGetProductInfoW` (via `ctypes`) | The official Windows Installer API. Links to registry entries via the ProductCode GUID. |
| MSI (avoided) | WMI `Win32_Product` | **Deliberately not primary.** Enumerating `Win32_Product` triggers an MSI *consistency check / reconfiguration* of every product (can repair installs, is slow). Acceptable only as an explicit last resort. |
| AppX/MSIX | `Get-AppxPackage` + `Get-StartApps` (PowerShell) | The underlying WinRT `Windows.Management.Deployment.PackageManager` surface is impractical to drive from `ctypes`, so its documented cmdlet wrapper is used as a fallback. `Get-StartApps` supplies the `AppUserModelId` needed to *launch* a Store app. |
| Services | `Get-CimInstance Win32_Service` (WMI) | Same `Win32_Service` class the `QueryServiceConfig` Win32 API exposes; read-only, no admin required for standard fields. |
| Startup | `winreg` Run/RunOnce + Startup folders | Run keys are registry; folder items are resolved with `WScript.Shell` COM (`.lnk`). |
| Scheduled tasks | `Get-ScheduledTask` (PowerShell) | Wraps the Task Scheduler COM/WMI API; exposes each action's `Execute`/`Arguments`. |
| Shortcuts | `WScript.Shell.CreateShortcut().TargetPath` (COM) | The canonical way to resolve a `.lnk` to its target executable. |
| PE metadata | `version.dll` `GetFileVersionInfoSizeW`/`GetFileVersionInfoW`/`VerQueryValueW` + COFF `IMAGE_FILE_MACHINE` header | Reads `CompanyName`, `ProductName`, `FileVersion`, and the machine architecture without loading the file as a module. |
| Signatures | `Get-AuthenticodeSignature` (PowerShell) | Calls the same `WinVerifyTrust` Authenticode machinery Windows uses; one batched process, never per-file. A missing signature is **not** treated as malicious. |

All PowerShell invocations are read-only queries, written to a temp `.ps1` and
run with `-NoProfile -ExecutionPolicy Bypass` (see `app/discovery/powershell.py`).

---

## 3. Matching / deduplication

The same program may arrive from Registry + MSI + AppX + Service + Shortcut.
Merging is **not** name-only; pairs are scored:

| Signal | Points |
|---|---|
| ProductCode equal | +100 |
| InstallLocation equal (normalised) | +90 |
| UninstallString → same executable | +80 |
| executable path equal | +70 |
| Publisher equal (normalised) | +50 |
| Name similar (token Jaccard, subset boost) | +40 |
| Version compatible (both present & matching) | +30 |

Thresholds:

* `>= 80` → merge (high confidence).
* `60–79` → candidate; merged only if an extra review rule also holds
  (same publisher **and** strong name overlap, same install location, or same
  uninstaller).
* `< 60` → never merged automatically.

Name similarity is **token-based** (Jaccard), not char-level `difflib`, so
"Google Chrome" and "Google Drive" (same vendor, different products) are not
merged.  Empty versions contribute nothing — absence of a version is not
evidence of sameness.

---

## 4. Classification

Each application is labelled, and the label decides whether it appears in the
default list:

| Class | Default visibility | Example |
|---|---|---|
| Normal Application | shown | Google Chrome |
| Runtime | shown | Visual C++ Redistributable |
| Unknown | shown | — |
| Update | hidden (toggle) | KB…, "Update for …", SystemComponent |
| System Component | hidden | resource packages, hosted services |
| Driver | hidden | `.sys` services |
| Framework | hidden | .NET Framework, SDKs, AppX framework packages |
| Language Pack | hidden | "… Language Pack" |

The picker has a **"Show updates & system components"** toggle to reveal the
hidden rows.

Confidence is `min(95, 55 + 10 × sources)` — it never reaches 100% because
discovery is inherently approximate.

---

## 5. Threading, timeouts, cancellation, permissions

* Scanners run in parallel on a `ThreadPoolExecutor` (default 6 workers).
* Each scanner has its own timeout; a timed-out or failing scanner is logged
  and skipped — the rest continue (`RegistryScanner FAILED` ⇒ MSI + AppX +
  Services still run).
* A `threading.Event` cancellation token is checked between scanners and after
  each result; the UI's progress dialog wires its **Cancel** button to it.
* The app runs without elevation.  `Get-AppxPackage -AllUsers` and some task /
  service properties can require admin; anything unavailable degrades to the
  accessible subset rather than failing the run.  Unavailable sources are
  surfaced through the log/errors list.
* The whole pipeline is read-only.

---

## 6. Logging

The engine emits the required lifecycle lines, streamed to the progress dialog
and (via the status signal) to the Logs page:

```
Discovery started
Registry scan started
Registry scan completed: 319 entries
MSI scan completed: 216 entries
AppX scan completed: 169 entries
Service scan completed: 314 entries
Deduplication completed
Signature scan completed: 118 files
Final applications: 340
```

No sensitive data is logged (no serial numbers, product IDs, or full
certificate subjects).

---

## 7. Known limits — false positives & false negatives

Discovery is **not** 100%.  These are the concrete, unavoidable cases:

**False positives (two entries wrongly merged):**

* Two programs from the same vendor installed into the **same directory** can
  exceed the merge threshold if their names also overlap.
* An auto-updater that registers its own uninstall entry next to the parent app
  can merge with the parent (usually harmless — it *is* part of that product).
* Electron apps that register under a generic name with no icon can only be
  matched by name/publisher, which is the weakest signal.

**False negatives (a real program is missing or split):**

* **Portable apps** never register in the uninstall keys; they only appear when
  the optional Portable scanner is enabled and pointed at the right folder.
* Programs that register **only** a `SystemComponent`/`ParentKeyName` entry with
  no `DisplayName` are dropped as top-level programs (correctly — they are
  sub-components).
* Some **uninstaller-only** entries point at `Update.exe`/`Setup.exe` with no
  icon or shortcut; they are discovered but may have **no launch path**, so they
  appear greyed-out (can't be added to a profile).  Example: apps that launch
  via `Update.exe --processStart App.exe` (Discord, some Electron apps).
* Per-user MSI products advertised but never installed, and provisioned AppX
  packages for other users, may be invisible without elevation.
* `svchost`-hosted services and kernel drivers are correctly shown as system
  components, not launchable programs.
* Custom/nonstandard installers that write to undocumented registry locations
  are invisible to *every* uninstaller (Revo included) without a filesystem
  scan — which this engine deliberately avoids in normal mode to prevent the
  false-positive flood of treating every `.exe` as a program.

**Signatures:** an unsigned executable is **not** flagged as suspicious; the
signature only raises confidence in identity, per the design.

---

## 8. Running the tests

```powershell
python -m unittest discover -s tests -v
```

The suite covers command-line tokenising, GUID/name/version normalisation,
matching thresholds, dedup merging, classification, and PE parsing, plus fast
Windows integration checks for the registry and MSI scanners.

To run a live discovery from a script:

```python
from app.discovery import discover
result = discover(on_log=print)
for app in result.apps:
    if app.surfaceable:
        print(app.name, app.architecture, app.launch_path)
```
