"""Profile storage and console-mode orchestration.

A profile bundles everything one "press the button" experience needs: the
display layout, the default audio device, and the applications to launch.
Profiles live in ``profiles/profiles.json`` next to the app:

    {
      "profiles": [
        {
          "name": "TV Mode",
          "display": {
            "primary": "\\\\.\\DISPLAY2",
            "monitors": [{"id": 1, "name": "\\\\.\\DISPLAY1", "width": 1920, ...}]
          },
          "audio": {"id": "{0.0.0.00000000}.{guid}", "name": "HDMI Output"},
          "apps": ["C:\\\\emulators\\\\retroarch.exe"],
          "close_apps_on_exit": true
        }
      ]
    }

``audio`` also accepts a bare device-name string for hand-written files; it is
normalised to the dict form on load.
"""

import json
import os
import subprocess
import threading
from pathlib import Path

from app.managers.paths import default_profiles_dir

# Keep launched apps in their own process group so we can terminate them
# without signalling ConsoleMode itself.
_CREATE_NEW_PROCESS_GROUP = 0x00000200

def new_profile(name="New Profile"):
    """An empty profile in the canonical schema."""
    return {
        "name": name,
        "display": {"primary": None, "monitors": []},
        "audio": {"id": None, "name": None},
        "apps": [],
        "close_apps_on_exit": True,
        "move_apps_to_primary": True,
    }

def _normalise(profile):
    """Fill in missing keys and coerce legacy shapes to the canonical schema."""
    clean = new_profile(str(profile.get("name") or "Unnamed Profile"))

    display = profile.get("display")
    if isinstance(display, dict):
        clean["display"] = {
            "primary": display.get("primary"),
            "monitors": [m for m in display.get("monitors", []) if isinstance(m, dict)],
        }

    audio = profile.get("audio")
    if isinstance(audio, dict):
        clean["audio"] = {"id": audio.get("id"), "name": audio.get("name")}
    elif isinstance(audio, str) and audio.strip():
        # Legacy/hand-written form: just the friendly name.
        clean["audio"] = {"id": None, "name": audio.strip()}

    apps = profile.get("apps")
    if isinstance(apps, list):
        clean["apps"] = [str(a) for a in apps if str(a).strip()]

    clean["close_apps_on_exit"] = bool(profile.get("close_apps_on_exit", True))
    clean["move_apps_to_primary"] = bool(profile.get("move_apps_to_primary", True))
    return clean

class ProfileManager:
    """Loads, stores and runs profiles.

    Mutating methods write to disk immediately, so the JSON on disk is always
    what the UI is showing.
    """

    def __init__(self, profiles_dir=None):
        self.profiles_dir = Path(profiles_dir) if profiles_dir else default_profiles_dir()
        self.profiles_file = self.profiles_dir / "profiles.json"
        self.profiles = []

        # Populated while a profile is active, so we can undo console mode.
        self.active_profile_name = None
        self._processes = []
        self._previous_state = None

        self.load()

    # ---------- persistence ----------
    def load(self):
        """Read profiles.json. A missing or unreadable file yields no profiles."""
        self.profiles = []
        if not self.profiles_file.exists():
            return self.profiles

        try:
            with open(self.profiles_file, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            # A corrupt file must not stop the app from starting; the next
            # save rewrites it.
            return self.profiles

        raw = data.get("profiles", []) if isinstance(data, dict) else data
        if isinstance(raw, list):
            self.profiles = [_normalise(p) for p in raw if isinstance(p, dict)]
        return self.profiles

    def set_profiles_dir(self, path):
        """Point the manager at a different profiles folder and reload it.

        The folder is created if it does not exist yet.  Returns
        ``(success, message)``; the profiles in memory are only replaced on
        success so a failed switch never loses the current list.
        """
        try:
            directory = Path(path).expanduser()
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            return False, "Cannot use '%s' as the profiles folder: %s" % (path, error)

        self.profiles_dir = directory
        self.profiles_file = directory / "profiles.json"
        self.load()
        return True, "Profiles folder is now %s." % directory

    def save(self):
        """Write profiles.json atomically. Returns ``(success, message)``."""
        try:
            self.profiles_dir.mkdir(parents=True, exist_ok=True)
            temp_file = self.profiles_file.with_suffix(".json.tmp")
            with open(temp_file, "w", encoding="utf-8") as handle:
                json.dump({"profiles": self.profiles}, handle, indent=2)
            # os.replace is atomic, so a crash mid-write cannot truncate the
            # real file.
            os.replace(temp_file, self.profiles_file)
        except OSError as error:
            return False, "Could not save profiles: %s" % error
        return True, "Profiles saved."

    # ---------- lookup ----------
    def names(self):
        return [p["name"] for p in self.profiles]

    def get(self, name):
        for profile in self.profiles:
            if profile["name"] == name:
                return profile
        return None

    def _unique_name(self, base):
        """``base``, or ``base (2)``, ``base (3)``... if already taken."""
        existing = set(self.names())
        if base not in existing:
            return base
        counter = 2
        while "%s (%d)" % (base, counter) in existing:
            counter += 1
        return "%s (%d)" % (base, counter)

    # ---------- CRUD ----------
    def create(self, name="New Profile", display_manager=None, audio_manager=None):
        """Add a profile, seeded with the current system state when managers
        are supplied. Returns the new profile."""
        profile = new_profile(self._unique_name(name))
        if display_manager is not None or audio_manager is not None:
            self.capture_current_state(profile, display_manager, audio_manager)
        self.profiles.append(profile)
        self.save()
        return profile

    def update(self, name, profile):
        """Replace the profile stored under ``name``. Returns ``(success, message)``."""
        for index, existing in enumerate(self.profiles):
            if existing["name"] == name:
                self.profiles[index] = _normalise(profile)
                return self.save()
        return False, "Profile '%s' no longer exists." % name

    def rename(self, old_name, new_name):
        """Returns ``(success, message)``."""
        new_name = (new_name or "").strip()
        if not new_name:
            return False, "A profile needs a name."

        profile = self.get(old_name)
        if profile is None:
            return False, "Profile '%s' no longer exists." % old_name
        if new_name != old_name and self.get(new_name) is not None:
            return False, "A profile named '%s' already exists." % new_name

        profile["name"] = new_name
        if self.active_profile_name == old_name:
            self.active_profile_name = new_name
        return self.save()

    def duplicate(self, name):
        """Copy a profile under a free name. Returns the copy, or None."""
        profile = self.get(name)
        if profile is None:
            return None
        copy = json.loads(json.dumps(profile))  # deep copy of plain JSON data
        copy["name"] = self._unique_name("%s (copy)" % name)
        self.profiles.append(copy)
        self.save()
        return copy

    def delete(self, name):
        """Returns ``(success, message)``."""
        profile = self.get(name)
        if profile is None:
            return False, "Profile '%s' no longer exists." % name
        self.profiles.remove(profile)
        if self.active_profile_name == name:
            self.active_profile_name = None
        return self.save()

    # ---------- capture ----------
    def capture_current_state(self, profile, display_manager=None, audio_manager=None):
        """Overwrite a profile's display/audio settings with the live ones."""
        if display_manager is not None:
            profile["display"] = display_manager.capture_layout()

        if audio_manager is not None and audio_manager.is_available():
            device = audio_manager.get_default_device()
            if device:
                profile["audio"] = {"id": device["id"], "name": device["name"]}
        return profile

    # ---------- launching ----------
    def launch(self, name, display_manager=None, audio_manager=None):
        """Enter console mode with a profile.

        Applies display settings, switches audio, then starts the profile's
        apps.  A failing step is reported but does not abort the rest — a
        missing emulator should not leave the TV unconfigured.

        Returns ``(success, messages)`` where ``messages`` is a list of lines
        suitable for the log/status area.
        """
        profile = self.get(name)
        if profile is None:
            return False, ["Profile '%s' no longer exists." % name]

        messages = []
        success = True

        # Snapshot what we are about to change so exit_console_mode can undo it.
        self._previous_state = self._snapshot_state(display_manager, audio_manager)

        if display_manager is not None and profile["display"].get("monitors"):
            ok, message = display_manager.apply_display_config(profile["display"])
            messages.append(message)
            success = success and ok

        audio = profile.get("audio") or {}
        if audio_manager is not None and (audio.get("id") or audio.get("name")):
            ok, message = audio_manager.set_default_device(
                audio.get("id"), fallback_name=audio.get("name")
            )
            messages.append(message)
            success = success and ok

        for app_path in profile.get("apps", []):
            ok, message = self._start_app(
                app_path, move_to_primary=profile.get("move_apps_to_primary", True)
            )
            messages.append(message)
            success = success and ok

        self.active_profile_name = name
        return success, messages

    def _start_app(self, app_path, move_to_primary=True):
        """Start one executable (or a ``shell:AppsFolder\\`` Store app).

        When ``move_to_primary`` is set, a daemon thread watches for the app's
        window and drags it onto the primary display (see
        :mod:`app.managers.window_manager`).  Store apps are launched through
        Explorer, which exits immediately, so their windows cannot be matched
        to a process and are left alone.

        Returns ``(success, message)``.
        """
        raw = os.path.expandvars(str(app_path))

        # Store (AppX/MSIX) apps are launched through the shell target, e.g.
        # ``shell:AppsFolder\\Microsoft.WindowsCalculator_8wekyb3d8bbwe!App``.
        if raw.lower().startswith("shell:"):
            return self._start_shell_app(raw)

        path = Path(raw)
        if not path.exists():
            return False, "Not found, skipped: %s" % app_path

        try:
            process = subprocess.Popen(
                [str(path)],
                # Emulators and launchers routinely expect to run from their
                # own folder (config, cores, BIOS files live there).
                cwd=str(path.parent),
                creationflags=_CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            )
        except OSError as error:
            return False, "Failed to launch %s: %s" % (path.name, error)

        self._processes.append(process)
        if move_to_primary:
            self._watch_window_placement(process)
        return True, "Launched %s." % path.name

    def _watch_window_placement(self, process):
        """Keep a launched app's window on the primary display while it opens.

        Playnite and similar launchers restore the window position they were
        last closed at, which ignores the primary display entirely, so the
        profile can apply correctly and the app still open on the wrong
        screen.  The watcher runs on a daemon thread so the launch itself is
        not delayed, and only nudges each window during its first moments.
        """
        try:
            from app.managers.window_manager import move_process_to_primary
        except ImportError:
            return  # non-Windows environment

        threading.Thread(
            target=move_process_to_primary,
            args=(process.pid,),
            daemon=True,
        ).start()

    def _start_shell_app(self, target):
        """Launch a ``shell:AppsFolder`` target through Explorer.

        Explorer hands the launch to the shell and exits immediately, so the
        Store app's own process is not tracked for termination on console-mode
        exit.  Returns ``(success, message)``.
        """
        try:
            process = subprocess.Popen(
                ["explorer.exe", target],
                creationflags=_CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            )
        except OSError as error:
            return False, "Failed to launch %s: %s" % (target, error)

        self._processes.append(process)
        return True, "Launched %s." % target

    def _snapshot_state(self, display_manager=None, audio_manager=None):
        """Record display layout and default audio device before a launch."""
        state = {"display": None, "audio": None}
        if display_manager is not None:
            state["display"] = display_manager.capture_layout()
        if audio_manager is not None and audio_manager.is_available():
            state["audio"] = audio_manager.get_default_device()
        return state

    # ---------- exiting ----------
    def exit_console_mode(self, display_manager=None, audio_manager=None,
                          restore_state=True):
        """Leave console mode.

        Terminates the apps this manager started (when the profile asks for it)
        and restores the display/audio state captured at launch.

        Returns ``(success, messages)``.
        """
        messages = []
        success = True

        profile = self.get(self.active_profile_name) if self.active_profile_name else None
        if profile is None or profile.get("close_apps_on_exit", True):
            closed, failed = self.terminate_apps()
            if closed:
                messages.append("Closed %d application(s)." % closed)
            if failed:
                messages.append("Could not close %d application(s)." % failed)
                success = False
        else:
            self._processes = [p for p in self._processes if p.poll() is None]
            messages.append("Left this profile's applications running.")

        if restore_state and self._previous_state:
            previous = self._previous_state
            if display_manager is not None and previous.get("display"):
                ok, message = display_manager.apply_display_config(previous["display"])
                messages.append("Restored displays: %s" % message)
                success = success and ok

            audio = previous.get("audio")
            if audio_manager is not None and audio:
                ok, message = audio_manager.set_default_device(
                    audio.get("id"), fallback_name=audio.get("name")
                )
                messages.append("Restored audio: %s" % message)
                success = success and ok

        self._previous_state = None
        self.active_profile_name = None
        return success, messages

    def terminate_apps(self, timeout=5):
        """Stop every process this manager started.

        Asks politely first, then kills whatever is still alive after
        ``timeout`` seconds. Returns ``(closed_count, failed_count)``.
        """
        closed = 0
        failed = 0

        for process in self._processes:
            if process.poll() is not None:
                continue  # already exited on its own
            try:
                process.terminate()
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=timeout)
                closed += 1
            except OSError:
                failed += 1

        self._processes = []
        return closed, failed

    def running_apps(self):
        """How many launched apps are still alive."""
        return sum(1 for p in self._processes if p.poll() is None)
