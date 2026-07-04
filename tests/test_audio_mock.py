# Translator Lower Third for vMix
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""Audio tests (Milestone 3): mock device list, fake chunks, lifecycle, levels.

No test touches real hardware: sounddevice is replaced with a fake module
in sys.modules (the import in the audio modules is lazy precisely for this).
"""

from __future__ import annotations

import struct
import sys
import types

import pytest

from app.audio.devices import (
    AudioInputError,
    list_input_devices,
    resolve_device_index,
)
from app.audio.input import FakeAudioInput, SoundDeviceAudioInput
from app.audio.levels import peak_level, rms_level
from app.services import LiveAppServices

# ---------------------------------------------------------------- FakeAudioInput


def test_fake_device_list():
    devices = FakeAudioInput().list_devices()
    assert len(devices) == 2
    assert devices[0].default is True
    assert devices[1].channels == 2


def test_fake_chunks_are_delivered():
    audio = FakeAudioInput()
    received: list[bytes] = []
    audio.start(None, 16000, 1, received.append)
    audio.feed(b"\x00\x01" * 100)
    audio.feed(b"\x02\x03" * 100)
    assert len(received) == 2
    assert received[0] == b"\x00\x01" * 100


def test_start_stop_lifecycle():
    audio = FakeAudioInput()
    assert not audio.is_running()
    audio.start("Mic finto", 16000, 1, lambda chunk: None)
    assert audio.is_running()
    assert audio.started_with == {
        "device_id": "Mic finto",
        "sample_rate": 16000,
        "channels": 1,
    }
    audio.stop()
    assert not audio.is_running()
    audio.feed(b"\x00\x00")  # after stop nothing should arrive nor blow up


# ---------------------------------------------------------------- levels


def _pcm16(*values: int) -> bytes:
    return struct.pack(f"<{len(values)}h", *values)


def test_rms_level_silence_is_zero():
    assert rms_level(_pcm16(0, 0, 0, 0)) == 0.0
    assert rms_level(b"") == 0.0


def test_rms_level_full_scale_near_one():
    level = rms_level(_pcm16(32767, -32768, 32767, -32768))
    assert 0.95 <= level <= 1.0


def test_rms_level_mid_signal():
    level = rms_level(_pcm16(16384, -16384, 16384, -16384))
    assert 0.45 <= level <= 0.55


def test_peak_level():
    assert peak_level(_pcm16(0, 0)) == 0.0
    assert peak_level(b"") == 0.0
    assert peak_level(_pcm16(0, -32768, 100)) == 1.0


# ---------------------------------------------------------------- fake sounddevice


class _FakeRawStream:
    """Stand-in for sd.RawInputStream that records the life cycle."""

    instances: list[_FakeRawStream] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.active = False
        self.closed = False
        _FakeRawStream.instances.append(self)

    def start(self) -> None:
        self.active = True

    def stop(self) -> None:
        self.active = False

    def close(self) -> None:
        self.closed = True

    def emit(self, chunk: bytes) -> None:
        self.kwargs["callback"](chunk, len(chunk) // 2, None, None)


def _install_fake_sounddevice(monkeypatch, devices, default_input=None, raw_stream=None):
    fake = types.ModuleType("sounddevice")

    def query_devices(device=None, kind=None):
        if kind == "input":
            if default_input is None:
                raise fake.PortAudioError("no default input")
            return devices[default_input]
        return devices

    fake.query_devices = query_devices
    fake.PortAudioError = type("PortAudioError", (Exception,), {})
    fake.RawInputStream = raw_stream or _FakeRawStream
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    return fake


_DEVICES = [
    {"index": 0, "name": "Microfono WASAPI", "max_input_channels": 1, "hostapi": 1},
    {"index": 1, "name": "Uscita cuffie", "max_input_channels": 0, "hostapi": 1},
    {"index": 2, "name": "Mixer WASAPI", "max_input_channels": 2, "hostapi": 1},
    {"index": 3, "name": "Microfono MME", "max_input_channels": 1, "hostapi": 0},
]


def test_list_input_devices_filters_outputs_and_hostapi(monkeypatch):
    _install_fake_sounddevice(monkeypatch, _DEVICES, default_input=0)
    devices = list_input_devices()
    # stable id = name; the volatile PortAudio index stays available separately
    assert [device.id for device in devices] == ["Microfono WASAPI", "Mixer WASAPI"]
    assert [device.index for device in devices] == [0, 2]
    assert devices[0].default is True
    assert devices[1].default is False


def test_list_input_devices_normalizes_messy_driver_names(monkeypatch):
    messy = [
        {
            "index": 0,
            "name": "Headset (@System32\\drivers\\bt.sys,#2;%1 Hands-Free%0\n;(Buds))",
            "max_input_channels": 1,
            "hostapi": 0,
        }
    ]
    _install_fake_sounddevice(monkeypatch, messy, default_input=0)
    devices = list_input_devices()
    assert "\n" not in devices[0].name
    assert "  " not in devices[0].name
    assert devices[0].id == devices[0].name


def test_list_input_devices_without_default_lists_all_inputs(monkeypatch):
    _install_fake_sounddevice(monkeypatch, _DEVICES, default_input=None)
    devices = list_input_devices()
    assert [device.index for device in devices] == [0, 2, 3]
    assert all(device.default is False for device in devices)


def test_list_input_devices_error_is_operator_readable(monkeypatch):
    fake = types.ModuleType("sounddevice")

    def query_devices(device=None, kind=None):
        raise RuntimeError("PortAudio esploso")

    fake.query_devices = query_devices
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    with pytest.raises(AudioInputError):
        list_input_devices()


# ---------------------------------------------------------------- resolve


def test_resolve_none_is_system_default(monkeypatch):
    assert resolve_device_index(None) is None


def test_resolve_int_passes_through():
    # hand-edited config or mock: no enumeration needed
    assert resolve_device_index(7) == 7


def test_resolve_name_to_current_index(monkeypatch):
    _install_fake_sounddevice(monkeypatch, _DEVICES, default_input=0)
    assert resolve_device_index("Mixer WASAPI") == 2


def test_resolve_missing_device_raises_operator_error(monkeypatch):
    _install_fake_sounddevice(monkeypatch, _DEVICES, default_input=0)
    with pytest.raises(AudioInputError) as excinfo:
        resolve_device_index("Microfono USB scollegato")
    assert "non è più disponibile" in str(excinfo.value)


# ---------------------------------------------------------------- SoundDeviceAudioInput


def test_sounddevice_input_start_stop(monkeypatch):
    _FakeRawStream.instances.clear()
    _install_fake_sounddevice(monkeypatch, _DEVICES, default_input=0)
    audio = SoundDeviceAudioInput()
    received: list[bytes] = []

    audio.start("Mixer WASAPI", 16000, 1, received.append)
    assert audio.is_running()
    stream = _FakeRawStream.instances[-1]
    assert stream.kwargs["device"] == 2  # name resolved to the current index
    assert stream.kwargs["samplerate"] == 16000
    assert stream.kwargs["channels"] == 1
    assert stream.kwargs["dtype"] == "int16"
    assert stream.kwargs["blocksize"] == 1600  # 100 ms at 16 kHz

    stream.emit(b"\x01\x02" * 10)
    assert received == [b"\x01\x02" * 10]

    audio.stop()
    assert not audio.is_running()
    assert stream.closed is True
    # after stop the callback must no longer forward
    stream.emit(b"\x03\x04")
    assert len(received) == 1


def test_sounddevice_input_open_failure_raises_operator_error(monkeypatch):
    class BrokenStream:
        def __init__(self, **kwargs) -> None:
            raise RuntimeError("device unavailable")

    _install_fake_sounddevice(monkeypatch, _DEVICES, default_input=0, raw_stream=BrokenStream)
    audio = SoundDeviceAudioInput()
    with pytest.raises(AudioInputError) as excinfo:
        audio.start(None, 16000, 1, lambda chunk: None)
    assert "ingresso audio" in str(excinfo.value)
    assert not audio.is_running()


def test_sounddevice_input_start_failure_closes_opened_stream(monkeypatch):
    # regression: if open succeeds but start() fails, the stream must be closed or
    # the device stays busy until the app is closed
    class StartFailsStream(_FakeRawStream):
        def start(self) -> None:
            raise RuntimeError("Pa_StartStream failed")

    _FakeRawStream.instances.clear()
    _install_fake_sounddevice(
        monkeypatch, _DEVICES, default_input=0, raw_stream=StartFailsStream
    )
    audio = SoundDeviceAudioInput()
    with pytest.raises(AudioInputError):
        audio.start(None, 16000, 1, lambda chunk: None)
    assert not audio.is_running()
    assert _FakeRawStream.instances[-1].closed is True


# ---------------------------------------------------------------- LiveAudioAppServices


def test_live_services_level_plumbing():
    audio = FakeAudioInput()
    services = LiveAppServices(audio)
    levels: list[float] = []

    result = services.start_audio_monitor("Mic finto", levels.append)
    assert result.ok is True
    audio.feed(_pcm16(*([16384, -16384] * 800)))  # half-scale signal
    services.stop_audio_monitor()

    assert len(levels) == 1
    assert 0.45 <= levels[0] <= 0.55  # rms_level applied to the chunk
    assert not audio.is_running()


def test_live_services_start_failure_becomes_service_result():
    class BrokenAudio(FakeAudioInput):
        def start(self, device_id, sample_rate, channels, on_chunk):
            raise AudioInputError("Impossibile aprire l'ingresso audio selezionato")

    services = LiveAppServices(BrokenAudio())
    result = services.start_audio_monitor(None, lambda level: None)
    assert result.ok is False
    assert "ingresso audio" in result.message


def test_live_services_device_list_failure_returns_empty(caplog):
    class BrokenAudio(FakeAudioInput):
        def list_devices(self):
            raise AudioInputError("Impossibile leggere l'elenco dei dispositivi audio")

    services = LiveAppServices(BrokenAudio())
    with caplog.at_level("WARNING", logger="app.services"):
        assert services.list_audio_devices() == []
    assert any("dispositivi audio" in record.message for record in caplog.records)


def test_live_services_uses_real_device_list():
    services = LiveAppServices(FakeAudioInput())
    devices = services.list_audio_devices()
    assert [device.id for device in devices] == ["Mic finto", "Mixer finto"]
