# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""Audio device model and enumeration of Windows inputs.

PortAudio indices change every time a device is plugged/unplugged: the config
persists the normalized NAME (AudioDevice.id), which is resolved to the current
index only when capture starts.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.i18n import t


class AudioInputError(Exception):
    """Audio error with an operator-readable message (in Italian)."""


@dataclass
class AudioDevice:
    id: int | str
    """Stable identifier to persist in config (normalized name)."""
    name: str
    channels: int
    default: bool = False
    index: int | None = None
    """Current PortAudio index: volatile, never to be saved."""


def list_input_devices() -> list[AudioDevice]:
    """List the audio inputs visible to Windows.

    Windows exposes the same physical device on multiple host APIs (MME,
    DirectSound, WASAPI…): to avoid confusing the operator, we filter on the
    host API of the default input device. sounddevice is imported inside the
    try: loading the PortAudio DLL can fail (incomplete build, blocked DLL)
    and must become a readable error, not a crash.
    """
    try:
        import sounddevice as sd

        devices = sd.query_devices()
    except Exception as exc:
        raise AudioInputError(t("audio.list_failed")) from exc

    default_index: int | None = None
    default_hostapi: int | None = None
    try:
        default_info = sd.query_devices(kind="input")
        default_index = default_info["index"]
        default_hostapi = default_info["hostapi"]
    except Exception:
        pass  # no default input: list all inputs

    result: list[AudioDevice] = []
    for info in devices:
        if info["max_input_channels"] <= 0:
            continue
        if default_hostapi is not None and info["hostapi"] != default_hostapi:
            continue
        # drivers (especially Bluetooth) report names with newlines and system
        # strings: normalize whitespace for the dropdown and persistence
        name = " ".join(info["name"].split())
        result.append(
            AudioDevice(
                id=name,
                name=name,
                channels=info["max_input_channels"],
                default=info["index"] == default_index,
                index=info["index"],
            )
        )
    return result


def resolve_device_index(device_id: int | str | None) -> int | None:
    """Convert the saved device_id to this session's PortAudio index.

    None = system default input. Ints pass through unchanged (hand-edited
    config or mocks). Names are looked up among the current inputs; if the
    device is gone, the error explains to the operator what to do.
    """
    if device_id is None:
        return None
    if isinstance(device_id, int):
        return device_id
    for device in list_input_devices():
        if device.id == device_id:
            return device.index
    raise AudioInputError(t("audio.saved_device_unavailable", device_id=device_id))
