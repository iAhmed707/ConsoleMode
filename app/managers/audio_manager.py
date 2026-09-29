"""Audio output device listing and switching.

Listing uses ``pycaw``'s public wrapper around IMMDeviceEnumerator.  Switching
the default device has no public API on Windows, so we call the undocumented
``IPolicyConfig`` COM interface — the same one the Sound control panel uses.
That interface is declared here rather than taken from pycaw so the code does
not depend on pycaw's internals changing between versions.

pycaw/comtypes are imported lazily: if they are missing the whole manager
degrades to "unavailable" and the UI shows why, instead of the app failing to
start.
"""

import ctypes

# EDataFlow / DEVICE_STATE / ERole values from mmdeviceapi.h. Used as raw ints
# so we do not depend on which pycaw module happens to export the enums.
E_RENDER = 0
DEVICE_STATE_ACTIVE = 0x00000001
ROLES = (0, 1, 2)  # eConsole, eMultimedia, eCommunications

_IMPORT_ERROR = None

try:
    import comtypes
    from comtypes import CLSCTX_ALL, COMMETHOD, GUID, HRESULT, IUnknown
    from pycaw.pycaw import AudioUtilities

    class IPolicyConfig(IUnknown):
        """Undocumented interface behind the Sound control panel.

        Only ``SetDefaultEndpoint`` is called.  The preceding methods still have
        to be declared, in order, because comtypes derives each method's vtable
        slot from its position.
        """

        _iid_ = GUID("{f8679f50-850a-41cf-9c72-430f290290c8}")
        _methods_ = (
            COMMETHOD([], HRESULT, "GetMixFormat"),
            COMMETHOD([], HRESULT, "GetDeviceFormat"),
            COMMETHOD([], HRESULT, "ResetDeviceFormat"),
            COMMETHOD([], HRESULT, "SetDeviceFormat"),
            COMMETHOD([], HRESULT, "GetProcessingPeriod"),
            COMMETHOD([], HRESULT, "SetProcessingPeriod"),
            COMMETHOD([], HRESULT, "GetShareMode"),
            COMMETHOD([], HRESULT, "SetShareMode"),
            COMMETHOD([], HRESULT, "GetPropertyValue"),
            COMMETHOD([], HRESULT, "SetPropertyValue"),
            COMMETHOD([], HRESULT, "SetDefaultEndpoint",
                      (["in"], ctypes.c_wchar_p, "device_id"),
                      (["in"], ctypes.c_int, "role")),
            COMMETHOD([], HRESULT, "SetEndpointVisibility"),
        )

    CLSID_POLICY_CONFIG_CLIENT = GUID("{870af99c-171d-4f9e-af0d-e63df40c2bc9}")

except ImportError as error:  # pragma: no cover - depends on the environment
    comtypes = None
    AudioUtilities = None
    IPolicyConfig = None
    CLSID_POLICY_CONFIG_CLIENT = None
    _IMPORT_ERROR = error

class AudioManager:
    """Lists audio output devices and sets the Windows default."""

    def __init__(self):
        self._devices = []

    # ---------- availability ----------
    def is_available(self):
        """False when pycaw/comtypes are not installed."""
        return AudioUtilities is not None

    def unavailable_reason(self):
        if self.is_available():
            return None
        return (
            "Audio switching needs the 'pycaw' and 'comtypes' packages "
            "(pip install pycaw comtypes). Details: %s" % _IMPORT_ERROR
        )

    # ---------- listing ----------
    def refresh(self):
        """Re-enumerate active output devices. Returns the device list."""
        self._devices = self._enumerate()
        return self._devices

    def get_devices(self):
        """Device dicts: ``id``, ``name``, ``is_default``."""
        if not self._devices:
            self.refresh()
        return self._devices

    def _enumerate(self):
        if not self.is_available():
            return []

        self._ensure_com()
        default_id = self._default_device_id()

        devices = []
        try:
            enumerator = AudioUtilities.GetDeviceEnumerator()
            collection = enumerator.EnumAudioEndpoints(E_RENDER, DEVICE_STATE_ACTIVE)
            for index in range(collection.GetCount()):
                device = AudioUtilities.CreateDevice(collection.Item(index))
                if device is None or not device.id:
                    continue
                devices.append({
                    "id": device.id,
                    "name": device.FriendlyName or device.id,
                    "is_default": device.id == default_id,
                })
        except Exception:
            # Older pycaw builds expose no usable enumerator; fall back to the
            # catch-all listing and filter out anything without a name.
            try:
                for device in AudioUtilities.GetAllDevices():
                    if not device.id or not device.FriendlyName:
                        continue
                    devices.append({
                        "id": device.id,
                        "name": device.FriendlyName,
                        "is_default": device.id == default_id,
                    })
            except Exception:
                return []

        devices.sort(key=lambda d: d["name"].lower())
        return devices

    def get_default_device(self):
        """The current default output device dict, or None."""
        default_id = self._default_device_id()
        if not default_id:
            return None
        for device in self.get_devices():
            if device["id"] == default_id:
                return device
        return {"id": default_id, "name": default_id, "is_default": True}

    def _default_device_id(self):
        """Endpoint id of the current default output, or None.

        pycaw changed GetSpeakers() to return an already-wrapped AudioDevice
        (it used to return a raw IMMDevice pointer), so both shapes are
        handled: wrap only when the result is not already wrapped.
        """
        if not self.is_available():
            return None
        try:
            self._ensure_com()
            speakers = AudioUtilities.GetSpeakers()
            if speakers is None:
                return None

            device_id = getattr(speakers, "id", None)
            if device_id is not None:
                return device_id

            device = AudioUtilities.CreateDevice(speakers)
            return device.id if device else None
        except Exception:
            return None

    # ---------- switching ----------
    def set_default_device(self, device_id, fallback_name=None):
        """Make a device the default output.

        ``device_id`` is the endpoint id stored in a profile.  If it is missing
        or the device has been re-enumerated (a TV that was switched off gets a
        new id on some drivers), ``fallback_name`` is matched instead.

        Returns ``(success, message)``.
        """
        if not self.is_available():
            return False, self.unavailable_reason()

        target = self._resolve_device(device_id, fallback_name)
        if target is None:
            label = fallback_name or device_id or "the profile's device"
            return False, "Audio device not found: %s." % label

        if target["is_default"]:
            return True, "Audio already set to %s." % target["name"]

        try:
            self._ensure_com()
            policy = comtypes.CoCreateInstance(
                CLSID_POLICY_CONFIG_CLIENT, IPolicyConfig, CLSCTX_ALL
            )
            # Set all three roles so media, system sounds and chat all follow.
            for role in ROLES:
                policy.SetDefaultEndpoint(target["id"], role)
        except Exception as error:
            return False, "Could not switch audio device: %s" % error

        self.refresh()
        return True, "Audio output set to %s." % target["name"]

    def _resolve_device(self, device_id, fallback_name=None):
        """Find a device by endpoint id, then by friendly name."""
        devices = self.refresh()
        if device_id:
            for device in devices:
                if device["id"] == device_id:
                    return device
        if fallback_name:
            wanted = fallback_name.strip().lower()
            for device in devices:
                if device["name"].strip().lower() == wanted:
                    return device
        return None

    # ---------- COM ----------
    @staticmethod
    def _ensure_com():
        """COM must be initialised on whichever thread makes the calls."""
        try:
            comtypes.CoInitialize()
        except Exception:
            # Already initialised on this thread (or a different apartment
            # model) - the calls below still work.
            pass
