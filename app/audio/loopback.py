# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""System-output (WASAPI loopback) capture.

Captures whatever is playing on a Windows output device (e.g. a YouTube video)
so it can be translated like a microphone input. The bundled sounddevice /
PortAudio build does not expose WASAPI loopback, so this uses the optional
``soundcard`` library (lazy import, injectable for tests), which resamples to the
requested rate and down-mixes to the requested channels for us.

The captured float32 frames are converted to little-endian PCM16 and emitted on
a worker thread, exactly like SoundDeviceAudioInput. Audio is never written to
disk.
"""

from __future__ import annotations

import logging
import threading

import numpy as np

from app.audio.devices import AudioDevice, AudioInputError
from app.audio.input import CHUNK_SECONDS, AudioInput, ChunkCallback
from app.i18n import t

logger = logging.getLogger("app.audio")


def _float_to_pcm16(data) -> bytes:
    """Convert soundcard's float32 frames (range [-1, 1]) to PCM16 bytes."""
    arr = np.clip(np.asarray(data, dtype="float32"), -1.0, 1.0)
    return (arr * 32767.0).astype("<i2").tobytes()


def _import_soundcard():
    import soundcard

    return soundcard


def loopback_devices(soundcard_module=None) -> list[AudioDevice]:
    """The output devices capturable via loopback, as selectable AudioDevices.

    Returns an empty list (never raises) when ``soundcard`` is not installed or
    enumeration fails, so the input dropdown simply omits the loopback options.
    """
    sc = soundcard_module
    if sc is None:
        try:
            sc = _import_soundcard()
        except Exception:
            return []
    try:
        mics = sc.all_microphones(include_loopback=True)
    except Exception:
        logger.debug("Enumerazione loopback non riuscita")
        return []
    result: list[AudioDevice] = []
    for mic in mics:
        if not getattr(mic, "isloopback", False):
            continue
        name = " ".join(str(mic.name).split())
        result.append(
            AudioDevice(
                id=str(mic.id),
                name=t("audio.loopback_device_name", name=name),
                channels=int(getattr(mic, "channels", 2) or 2),
                loopback=True,
            )
        )
    return result


class SoundcardLoopbackCapture(AudioInput):
    """AudioInput that captures a system output device via WASAPI loopback."""

    def __init__(self, soundcard_module=None) -> None:
        self._sc = soundcard_module
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._open_failed = False
        self._on_chunk: ChunkCallback | None = None

    # ------------------------------------------------------------------ AudioInput

    def list_devices(self) -> list[AudioDevice]:
        return loopback_devices(self._sc)

    def has_device(self, device_id: int | str | None) -> bool:
        if device_id is None:
            return False
        return any(device.id == device_id for device in self.list_devices())

    def start(
        self,
        device_id: int | str | None,
        sample_rate: int,
        channels: int,
        on_chunk: ChunkCallback,
    ) -> None:
        if self._thread is not None:
            self.stop()
        sc = self._require_soundcard()
        mic = self._find_loopback(sc, device_id)
        if mic is None:
            raise AudioInputError(t("audio.loopback_device_unavailable"))
        frames = int(sample_rate * CHUNK_SECONDS)
        self._on_chunk = on_chunk
        self._stop.clear()
        self._ready.clear()
        self._open_failed = False
        # Media Foundation objects are apartment-threaded: the recorder must be
        # opened, read AND closed on the same thread, so everything happens in
        # the worker. start() waits for the open to succeed/fail to report it.
        self._thread = threading.Thread(
            target=self._run,
            args=(mic, sample_rate, channels, frames),
            daemon=True,
            name="loopback-capture",
        )
        self._thread.start()
        if not self._ready.wait(timeout=5.0) or self._open_failed:
            self._stop.set()
            raise AudioInputError(t("audio.loopback_open_failed"))
        logger.info("Cattura loopback avviata (%s Hz, %s canali)", sample_rate, channels)

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        self._on_chunk = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=3.0)
        if thread is not None:
            logger.info("Cattura loopback fermata")

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------ internal

    def _require_soundcard(self):
        if self._sc is not None:
            return self._sc
        try:
            self._sc = _import_soundcard()
        except Exception as exc:
            raise AudioInputError(t("audio.loopback_not_installed")) from exc
        return self._sc

    @staticmethod
    def _find_loopback(sc, device_id):
        try:
            mics = sc.all_microphones(include_loopback=True)
        except Exception:
            return None
        for mic in mics:
            if getattr(mic, "isloopback", False) and str(mic.id) == device_id:
                return mic
        return None

    def _run(self, mic, sample_rate: int, channels: int, frames: int) -> None:
        # worker thread: open, read AND close the recorder here (Media Foundation
        # COM objects must stay on one thread). No GUI access from here.
        try:
            recorder = mic.recorder(
                samplerate=sample_rate, channels=channels, blocksize=frames
            )
        except Exception:
            logger.warning("Apertura loopback fallita")
            self._open_failed = True
            self._ready.set()
            return
        try:
            with recorder:
                self._ready.set()  # opened successfully
                while not self._stop.is_set():
                    try:
                        data = recorder.record(numframes=frames)
                    except Exception:
                        logger.warning("Lettura loopback interrotta")
                        break
                    callback = self._on_chunk
                    if callback is None:
                        break
                    callback(_float_to_pcm16(data))
        except Exception:
            logger.exception("Cattura loopback interrotta")
            self._open_failed = True
        finally:
            self._ready.set()  # unblock start() even if entering failed
