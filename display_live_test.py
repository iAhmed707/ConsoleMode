"""Live diagnosis of the primary-display flip on profile launch.

Replays the user's exact sequence against the real Windows display APIs:
  set FHD as primary -> capture -> apply_display_config (profile launch),
and reports which monitor is primary after every step, so we can see which
apply path (_apply_staged_layout vs _apply_primary_switch) misbehaves.

The original layout is always restored at the end.
"""

import json
import sys
import time
import traceback

from app.managers.display_manager import DisplayManager

SETTLE_SECONDS = 2.0


def monitor_lines(dm):
    lines = []
    for m in dm.refresh():
        lines.append(
            "    %-12s %-18s %dx%d @%3dHz  pos=(%5d,%5d)  primary=%s"
            % (m["name"], m.get("label") or "", m["width"], m["height"],
               m["refresh_rate"], m["x"], m["y"], m["is_primary"])
        )
    return lines


def show(title, dm):
    dm.refresh()
    primary = dm.get_primary()
    print("\n== %s ==" % title)
    print("\n".join(monitor_lines(dm)))
    print("    -> current primary:", primary["name"] if primary else None)


def find_by_resolution(dm, width, height):
    for m in dm.refresh():
        if m["width"] == width and m["height"] == height:
            return m["name"]
    return None


def main():
    dm = DisplayManager()

    baseline = dm.capture_layout()
    fhd = find_by_resolution(dm, 1920, 1080)   # LG ULTRAGEAR
    k2 = find_by_resolution(dm, 2560, 1440)    # MAS1-272K626
    print("FHD =", fhd, "| 2K =", k2)
    print("Baseline primary =", baseline["primary"])
    if not fhd or not k2:
        print("ABORT: could not find both the FHD and the 2K monitor. Nothing changed.")
        return

    # Trace which apply path runs and with which positions.
    orig_staged = dm._apply_staged_layout
    orig_ccd = dm._apply_positions_via_ccd

    def traced_staged(wanted, positions):
        print("[PATH] _apply_staged_layout (fallback) positions=%s"
              % sorted(positions.items()))
        return orig_staged(wanted, positions)

    def traced_ccd(positions):
        print("[PATH] _apply_positions_via_ccd (SetDisplayConfig) positions=%s"
              % sorted(positions.items()))
        return orig_ccd(positions)

    dm._apply_staged_layout = traced_staged
    dm._apply_positions_via_ccd = traced_ccd

    try:
        show("BASELINE", dm)

        # [A] What the user did: "Set as primary" on the FHD in the Displays page.
        ok, msg = dm.set_primary(fhd)
        print("\n[A] set_primary(%s) -> ok=%s msg=%r" % (fhd, ok, msg))
        time.sleep(SETTLE_SECONDS)
        show("After set_primary(FHD)", dm)

        # [B] Capture.
        captured = dm.capture_layout()
        print("\n[B] captured profile layout:")
        print(json.dumps(captured, indent=2))

        # [C] Profile launch with the primary unchanged -> staged path.
        print("\n[C] apply_display_config(captured)  [expect changing_primary=False]")
        ok, msg = dm.apply_display_config(captured)
        print("    -> ok=%s msg=%r" % (ok, msg))
        time.sleep(SETTLE_SECONDS)
        show("After launch-apply, case C (primary unchanged)", dm)

        # [D] Make the 2K primary again (as if the user switched back between
        # capture and launch), then launch -> primary-switch path.
        ok, msg = dm.set_primary(k2)
        print("\n[D] set_primary(%s) -> ok=%s msg=%r" % (k2, ok, msg))
        time.sleep(SETTLE_SECONDS)
        show("After set_primary(2K)", dm)

        ok, msg = dm.apply_display_config(captured)
        print("\n[E] apply_display_config(captured)  [expect changing_primary=True]")
        print("    -> ok=%s msg=%r" % (ok, msg))
        time.sleep(SETTLE_SECONDS)
        show("After launch-apply, case E (primary switch)", dm)

    except Exception:
        print("\nTEST ERROR:")
        traceback.print_exc()

    finally:
        # Always put the user's desktop back the way it was.
        print("\n== RESTORE ==")
        try:
            ok, msg = dm.apply_display_config(baseline)
            print("    restore -> ok=%s msg=%r" % (ok, msg))
        except Exception:
            traceback.print_exc()
        time.sleep(SETTLE_SECONDS)
        dm.refresh()
        primary = dm.get_primary()
        print("\n".join(monitor_lines(dm)))
        if primary and primary["name"] == baseline["primary"]:
            print("RESTORE OK: primary back to %s." % baseline["primary"])
        else:
            print("RESTORE MISMATCH: expected primary %s, got %s."
                  % (baseline["primary"], primary["name"] if primary else None))


if __name__ == "__main__":
    sys.exit(main())
