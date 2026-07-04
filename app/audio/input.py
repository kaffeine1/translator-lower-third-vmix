# Translator Lower Third for vMix
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""Audio capture: AudioInput interface and sounddevice implementation.

The emitted chunks are little-endian PCM16 at the requested sample rate
(default 16 kHz mono, the format expected by providers). The callback arrives
from the PortAudio thread: consumers must NOT touch the GUI from there.

Audio is never written to disk.
"""

from __future__ import annotations

import abc
import logging
from collections.abc import Callable

from app.audio.devices import (
    AudioDevice,
    AudioInputError,
    list_input_devices,
    resolve_device_index,
)

logger = logging.getLogger("app.audio")

ChunkCallback = Callable[[bytes], None]

# 100 ms of audio per chunk: responsive for the meter, efficient for providers
CHUNK_SECONDS = 0.1


class AudioInput(abc.ABC):
    """Captures audio on a worker thread and emits PCM16 chunks."""

    @abc.abstractmethod
    def list_devices(self) -> list[AudioDevice]: ...

    @abc.abstractmethod
    def start(
        self,
        device_id: int | str | None,
        sample_rate: int,
        channels: int,
        on_chunk: ChunkCallback,
    ) -> None: ...

    @abc.abstractmethod
    def stop(self) -> None: ...

    @abc.abstractmethod
    def is_running(self) -> bool: ...


class SoundDeviceAudioInput(AudioInput):
    """Capture via sounddevice/PortAudio.

    device_id None uses the Windows default input. If the device does not
    natively support the requested sample rate, PortAudio (in shared mode)
    converts it; otherwise start() raises AudioInputError with an
    understandable message.
    """

    def __init__(self) -> None:
        self._stream = None
        self._on_chunk: ChunkCallback | None = None

    def list_devices(self) -> list[AudioDevice]:
        return list_input_devices()

    def start(
        self,
        device_id: int | str | None,
        sample_rate: int,
        channels: int,
        on_chunk: ChunkCallback,
    ) -> None:
        if self._stream is not None:
            self.stop()
        # already raises a readable AudioInputError if the saved device
        # is no longer connected
        device_index = resolve_device_index(device_id)
        self._on_chunk = on_chunk
        stream = None
        try:
            import sounddevice as sd

            stream = sd.RawInputStream(
                device=device_index,
                samplerate=sample_rate,
                channels=channels,
                dtype="int16",
                blocksize=int(sample_rate * CHUNK_SECONDS),
                callback=self._callback,
            )
            stream.start()
        except Exception as exc:
            # without close() the open stream would keep the device busy
            # until the app is closed
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            self._on_chunk = None
            logger.warning("Apertura ingresso audio fallita: %s", type(exc).__name__)
            raise AudioInputError(
                "Impossibile aprire l'ingresso audio selezionato. "
                "Controlla che il dispositivo sia collegato, poi riprova "
                "o scegline un altro nelle Impostazioni."
            ) from exc
        self._stream = stream
        logger.info(
            "Cattura audio avviata (device=%s, %s Hz, %s canali)",
            "predefinito" if device_id is None else device_id,
            sample_rate,
            channels,
        )

    def _callback(self, indata, frames, time_info, status) -> None:
        # PortAudio thread: only copy and forward, no GUI and no per-chunk
        # logging (it arrives 10 times per second).
        callback = self._on_chunk
        if callback is not None:
            callback(bytes(indata))

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        self._on_chunk = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                logger.exception("Errore durante l'arresto della cattura audio")
            else:
                logger.info("Cattura audio fermata")

    def is_running(self) -> bool:
        return self._stream is not None and bool(self._stream.active)


class FakeAudioInput(AudioInput):
    """Fake implementation for tests and demos: chunks injected via feed().

    No hardware, no thread: feed() delivers the chunk synchronously to the
    callback registered by start().
    """

    def __init__(self) -> None:
        self._running = False
        self._on_chunk: ChunkCallback | None = None
        self.started_with: dict | None = None

    def list_devices(self) -> list[AudioDevice]:
        return [
            AudioDevice(id="Mic finto", name="Mic finto", channels=1, default=True, index=0),
            AudioDevice(id="Mixer finto", name="Mixer finto", channels=2, index=3),
        ]

    def start(
        self,
        device_id: int | str | None,
        sample_rate: int,
        channels: int,
        on_chunk: ChunkCallback,
    ) -> None:
        self.started_with = {
            "device_id": device_id,
            "sample_rate": sample_rate,
            "channels": channels,
        }
        self._on_chunk = on_chunk
        self._running = True

    def feed(self, chunk: bytes) -> None:
        """Deliver a chunk as the PortAudio thread would."""
        if self._running and self._on_chunk is not None:
            self._on_chunk(chunk)

    def stop(self) -> None:
        self._running = False
        self._on_chunk = None

    def is_running(self) -> bool:
        return self._running
