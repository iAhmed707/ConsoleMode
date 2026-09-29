"""Restore the 2K monitor to 2560x1440@240Hz (CCD path, HDR-safe)."""

import ctypes
import time
import traceback
from ctypes import wintypes

from app.managers.display_manager import (
    DISPLAYCONFIG_PATH_INFO,
    DISPLAYCONFIG_MODE_INFO,
    DISPLAYCONFIG_RATIONAL,
    DISPLAYCONFIG_SOURCE_DEVICE_NAME,
    DisplayManager,
    ERROR_SUCCESS,
    QDC_ONLY_ACTIVE_PATHS,
    DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME,
    SDC_APPLY,
    SDC_USE_SUPPLIED_DISPLAY_CONFIG,
    SDC_ALLOW_CHANGES,
    SDC_SAVE_TO_DATABASE,
)

TARGET_NAME = "\\\\.\\DISPLAY1"
WIDTH, HEIGHT, HZ = 2560, 1440, 240


def print_state(dm, title):
    dm.refresh()
    print("== %s ==" % title)
    for m in dm.get_monitor_info():
        print("    %-12s %dx%d @%3dHz pos=(%5d,%5d) primary=%s hdr=%s (%s)"
              % (m["name"], m["width"], m["height"], m["refresh_rate"],
                 m["x"], m["y"], m["is_primary"], m["hdr_enabled"], m["color_mode"]))


def set_refresh_ccd(target_name, hz):
    """Set one monitor's refresh rate via SetDisplayConfig (HDR-safe)."""
    u = ctypes.windll.user32
    u.GetDisplayConfigBufferSizes.argtypes = [
        wintypes.UINT, ctypes.POINTER(wintypes.UINT), ctypes.POINTER(wintypes.UINT)]
    u.GetDisplayConfigBufferSizes.restype = ctypes.c_long
    u.QueryDisplayConfig.argtypes = [
        wintypes.UINT, ctypes.POINTER(wintypes.UINT),
        ctypes.POINTER(DISPLAYCONFIG_PATH_INFO),
        ctypes.POINTER(wintypes.UINT),
        ctypes.POINTER(DISPLAYCONFIG_MODE_INFO), wintypes.LPVOID]
    u.QueryDisplayConfig.restype = ctypes.c_long
    u.DisplayConfigGetDeviceInfo.argtypes = [ctypes.c_void_p]
    u.DisplayConfigGetDeviceInfo.restype = ctypes.c_long
    u.SetDisplayConfig.argtypes = [
        wintypes.UINT, ctypes.POINTER(DISPLAYCONFIG_PATH_INFO),
        wintypes.UINT, ctypes.POINTER(DISPLAYCONFIG_MODE_INFO), wintypes.UINT]
    u.SetDisplayConfig.restype = ctypes.c_long

    path_count = wintypes.UINT()
    mode_count = wintypes.UINT()
    if u.GetDisplayConfigBufferSizes(QDC_ONLY_ACTIVE_PATHS,
                                     ctypes.byref(path_count),
                                     ctypes.byref(mode_count)) != ERROR_SUCCESS:
        return False, "GetDisplayConfigBufferSizes failed"

    paths = (DISPLAYCONFIG_PATH_INFO * path_count.value)()
    modes = (DISPLAYCONFIG_MODE_INFO * mode_count.value)()
    pc = wintypes.UINT(path_count.value)
    mc = wintypes.UINT(mode_count.value)
    if u.QueryDisplayConfig(QDC_ONLY_ACTIVE_PATHS, ctypes.byref(pc), paths,
                            ctypes.byref(mc), modes, None) != ERROR_SUCCESS:
        return False, "QueryDisplayConfig failed"

    touched = False
    for path in paths[:pc.value]:
        source = DISPLAYCONFIG_SOURCE_DEVICE_NAME()
        source.header.type = DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME
        source.header.size = ctypes.sizeof(source)
        source.header.adapterId = path.sourceInfo.adapterId
        source.header.id = path.sourceInfo.id
        if u.DisplayConfigGetDeviceInfo(ctypes.cast(ctypes.pointer(source), ctypes.c_void_p)) != ERROR_SUCCESS:
            continue
        if source.viewGdiDeviceName != target_name:
            continue

        mode_index = path.sourceInfo.modeInfoIdx
        if mode_index >= len(modes):
            continue
        modes[mode_index].u.sourceMode.width = WIDTH
        modes[mode_index].u.sourceMode.height = HEIGHT

        # Update the refresh in both places SetDisplayConfig reads it.
        ratio = DISPLAYCONFIG_RATIONAL(hz * 1000, 1000)
        path.targetInfo.refreshRate = ratio
        target_index = path.targetInfo.modeInfoIdx
        if target_index < len(modes):
            modes[target_index].u.targetMode.targetVideoSignalInfo.vSyncFreq = ratio
        touched = True

    if not touched:
        return False, "target display not found in active paths"

    flags = (SDC_APPLY | SDC_USE_SUPPLIED_DISPLAY_CONFIG
             | SDC_ALLOW_CHANGES | SDC_SAVE_TO_DATABASE)
    code = u.SetDisplayConfig(pc.value, paths, mc.value, modes, flags)
    if code != ERROR_SUCCESS:
        return False, "SetDisplayConfig failed with code %s" % code
    return True, "SetDisplayConfig applied %d Hz" % hz


def main():
    dm = DisplayManager()
    print_state(dm, "BEFORE")

    ok, msg = set_refresh_ccd(TARGET_NAME, HZ)
    print("CCD refresh set:", ok, msg)
    time.sleep(2.0)
    print_state(dm, "AFTER CCD ATTEMPT")

    target = dm.get_monitor(TARGET_NAME)
    if target and target["refresh_rate"] == HZ:
        print("RESTORED: %s is back at %d Hz." % (TARGET_NAME, HZ))
        return

    # Fallback: HDR off -> legacy mode change -> HDR back on.
    print("CCD attempt did not reach %d Hz; trying HDR-off fallback." % HZ)
    try:
        hdr_was_on = bool(dm.get_monitor(TARGET_NAME).get("hdr_enabled"))
        if hdr_was_on:
            print("  set_hdr off ->", dm.set_hdr(TARGET_NAME, False))
        ok, msg = dm.set_resolution(TARGET_NAME, WIDTH, HEIGHT, HZ)
        print("  set_resolution ->", ok, msg)
        if hdr_was_on:
            print("  set_hdr on  ->", dm.set_hdr(TARGET_NAME, True))
        time.sleep(2.0)
        print_state(dm, "AFTER FALLBACK")
        target = dm.get_monitor(TARGET_NAME)
        if target and target["refresh_rate"] == HZ:
            print("RESTORED: %s is back at %d Hz." % (TARGET_NAME, HZ))
        else:
            print("WARNING: could not restore %d Hz; still at %d Hz."
                  % (HZ, target["refresh_rate"] if target else 0))
    except Exception:
        traceback.print_exc()


if __name__ == "__main__":
    main()
