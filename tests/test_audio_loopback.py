# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""System-output (WASAPI loopback) capture tests.

No real audio: the ``soundcard`` library is faked/injected. These cover
enumeration, backend routing, the float32->PCM16 conversion and the capture
lifecycle, so nothing here needs a sound card or the optional dependency.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from app.audio.devices import AudioInputError
from app.audio.input import FakeAudioInput, SystemAudioInput
from app.audio.loopback import (
    SoundcardLoopbackCapture,
    _float_to_pcm16,
    loopback_devices,
)


class _FakeRecorder:
    def __init__(self, chunk) -> None:
        self._chunk = chunk
        self.entered = False
        self.exited = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *exc) -> bool:
        self.exited = True
        return False

    def record(self, numframes):
        time.sleep(0.005)  # throttle the capture loop in tests
        return self._chunk


class _FakeMic:
    def __init__(self, mic_id, name, isloopback, channels=2, recorder=None) -> None:
        self.id = mic_id
        self.name = name
        self.isloopback = isloopback
        self.channels = channels
        self._recorder = recorder

    def recorder(self, samplerate, channels, blocksize):
        return self._recorder


class _FakeSoundcard:
    def __init__(self, mics) -> None:
        self._mics = mics

    def all_microphones(self, include_loopback=False):
        return [m for m in self._mics if include_loopback or not m.isloopback]


def _soundcard(recorder=None):
    return _FakeSoundcard(
        [
            _FakeMic("mic-1", "Microfono", isloopback=False),
            _FakeMic("spk-1", "Altoparlanti Realtek", isloopback=True, recorder=recorder),
        ]
    )


# ---------------------------------------------------------------- enumeration


def test_loopback_devices_lists_only_loopback():
    devices = loopback_devices(_soundcard())
    assert len(devices) == 1
    device = devices[0]
    assert device.id == "spk-1"
    assert device.loopback is True
    assert "loopback" in device.name.lower()


def test_loopback_devices_missing_soundcard_returns_empty(monkeypatch):
    import app.audio.loopback as loopback

    def _no_soundcard():
        raise ImportError("no soundcard")

    monkeypatch.setattr(loopback, "_import_soundcard", _no_soundcard)
    assert loopback.loopback_devices() == []


def test_loopback_devices_enumeration_error_returns_empty():
    class _BadSoundcard:
        def all_microphones(self, include_loopback=False):
            raise RuntimeError("boom")

    assert loopback_devices(_BadSoundcard()) == []


# ---------------------------------------------------------------- conversion


def test_float_to_pcm16_clips_and_scales():
    data = np.array([[0.0], [1.0], [-1.0], [0.5], [2.0]], dtype="float32")
    pcm = np.frombuffer(_float_to_pcm16(data), dtype="<i2")
    assert pcm.tolist() == [0, 32767, -32767, 16383, 32767]  # 2.0 clipped to 1.0


# ---------------------------------------------------------------- routing


def test_system_audio_input_lists_mic_and_loopback():
    mic = FakeAudioInput()
    loopback = SoundcardLoopbackCapture(soundcard_module=_soundcard())
    system = SystemAudioInput(mic_input=mic, loopback=loopback)
    ids = [(d.id, d.loopback) for d in system.list_devices()]
    assert ("spk-1", True) in ids
    assert any(not is_loop for _id, is_loop in ids)  # at least one real input


def test_system_audio_input_routes_microphone_for_normal_device():
    mic = FakeAudioInput()
    loopback = SoundcardLoopbackCapture(soundcard_module=_soundcard())
    system = SystemAudioInput(mic_input=mic, loopback=loopback)
    system.start("Mic finto", 16000, 1, lambda _b: None)
    assert system._active is mic
    assert mic.is_running()
    system.stop()
    assert not system.is_running()


def test_system_audio_input_routes_loopback_for_output_device():
    chunk = np.full((4, 1), 0.5, dtype="float32")
    recorder = _FakeRecorder(chunk)
    loopback = SoundcardLoopbackCapture(soundcard_module=_soundcard(recorder))
    system = SystemAudioInput(mic_input=FakeAudioInput(), loopback=loopback)
    system.start("spk-1", 16000, 1, lambda _b: None)
    assert system._active is loopback
    assert loopback.is_running()
    system.stop()
    assert not loopback.is_running()


# ---------------------------------------------------------------- lifecycle


def test_loopback_capture_emits_pcm16_and_closes_recorder():
    chunk = np.full((4, 1), 0.5, dtype="float32")  # -> 16383 per sample
    recorder = _FakeRecorder(chunk)
    capture = SoundcardLoopbackCapture(soundcard_module=_soundcard(recorder))
    collected: list[bytes] = []
    capture.start("spk-1", 16000, 1, collected.append)
    assert recorder.entered is True

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and not collected:
        time.sleep(0.01)
    assert collected, "no audio chunk was emitted"
    assert np.frombuffer(collected[0], dtype="<i2").tolist() == [16383, 16383, 16383, 16383]

    capture.stop()
    assert recorder.exited is True
    assert not capture.is_running()


def test_loopback_start_unknown_device_raises():
    capture = SoundcardLoopbackCapture(soundcard_module=_soundcard())
    with pytest.raises(AudioInputError):
        capture.start("does-not-exist", 16000, 1, lambda _b: None)


def test_loopback_start_without_soundcard_raises(monkeypatch):
    import app.audio.loopback as loopback

    def _no_soundcard():
        raise ImportError("no soundcard")

    monkeypatch.setattr(loopback, "_import_soundcard", _no_soundcard)
    capture = loopback.SoundcardLoopbackCapture()  # no injected module
    with pytest.raises(AudioInputError):
        capture.start("spk-1", 16000, 1, lambda _b: None)
