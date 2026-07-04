# Translator Lower Third for vMix
# Autore: Michele Dipace <michele.dipace@kaffeine.net>
"""Cattura audio: interfaccia AudioInput e implementazione sounddevice.

I chunk emessi sono PCM16 little-endian al sample rate richiesto (default
16 kHz mono, il formato atteso dai provider). Il callback arriva dal thread
PortAudio: i consumatori NON devono toccare la GUI da lì.

L'audio non viene mai scritto su disco.
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

# 100 ms di audio per chunk: reattivo per il meter, efficiente per i provider
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
    """Cattura tramite sounddevice/PortAudio.

    device_id None usa l'ingresso predefinito di Windows. Se il dispositivo
    non supporta nativamente il sample rate richiesto, PortAudio (in shared
    mode) lo converte; in caso contrario start() solleva AudioInputError con
    un messaggio comprensibile.
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
        # solleva già AudioInputError leggibile se il dispositivo salvato
        # non è più collegato
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
            # senza close() lo stream aperto terrebbe occupato il dispositivo
            # fino alla chiusura dell'app
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
        # Thread PortAudio: solo copia e inoltro, niente GUI e niente log
        # per-chunk (arriva 10 volte al secondo).
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
    """Implementazione finta per test e demo: chunk iniettati con feed().

    Nessun hardware, nessun thread: feed() consegna il chunk in modo sincrono
    al callback registrato da start().
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
        """Consegna un chunk come farebbe il thread PortAudio."""
        if self._running and self._on_chunk is not None:
            self._on_chunk(chunk)

    def stop(self) -> None:
        self._running = False
        self._on_chunk = None

    def is_running(self) -> bool:
        return self._running
