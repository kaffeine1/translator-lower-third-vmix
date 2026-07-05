# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""FasterWhisperSpeechProvider — local (offline) speech recognition (v1.3).

A SpeechProvider: audio -> source text, run locally with Faster-Whisper (no
cloud, no API cost). Combine it with a TranslationProvider (local MarianMT or
cloud DeepL) inside a ComposedRealtimeProvider.

Faster-Whisper is not a streaming API: the engine buffers PCM16 audio and
transcribes complete segments on a worker thread, emitting each as a final
event. All Faster-Whisper logic lives here; the model "engine" is injectable so
tests run with a fake engine (no model download, no heavy dependency). The real
engine needs the optional ``faster-whisper`` package (see
requirements-optional.txt) and works best on a machine with an NVIDIA GPU.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from app.i18n import t
from app.providers.base import ProviderConfig, ProviderError, SpeechProvider

logger = logging.getLogger("app.providers.local_whisper")

# how much audio to accumulate before transcribing one segment
SEGMENT_SECONDS = 4.0
# hard cap on the audio backlog: if transcription is slower than realtime (common
# on CPU) the oldest audio is dropped rather than growing memory without bound
MAX_BUFFER_SECONDS = 30.0

DEFAULT_MODEL = "small"
DEFAULT_DEVICE = "cpu"

TextCb = Callable[[str], None]
EngineFactory = Callable[..., "object"]


class LocalWhisperError(ProviderError):
    """Local speech error with an operator-readable message (Italian)."""


class FasterWhisperSpeechProvider(SpeechProvider):
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        device: str = DEFAULT_DEVICE,
        engine_factory: EngineFactory | None = None,
    ) -> None:
        super().__init__()
        self._model = model
        self._device = device
        self._engine_factory = engine_factory or _make_real_engine
        self._engine: object | None = None

    async def connect(self, config: ProviderConfig) -> None:
        self._engine = self._engine_factory(
            model=self._model,
            device=self._device,
            sample_rate=config.sample_rate,
            language=config.source_language,
            on_partial=self._emit_partial,
            on_final=self._emit_final,
            on_error=self._emit_error,
        )
        self._engine.start()

    async def send_audio(self, chunk: bytes) -> None:
        if self._engine is not None:
            self._engine.push(chunk)

    async def close(self) -> None:
        engine, self._engine = self._engine, None
        if engine is not None:
            try:
                engine.stop()
            except Exception:
                logger.exception("Errore fermando Faster-Whisper")


def _make_real_engine(**kwargs) -> object:
    try:
        import numpy  # noqa: F401
        from faster_whisper import WhisperModel
    except ImportError:
        raise LocalWhisperError(t("local.whisper_not_installed")) from None
    return _WhisperEngine(WhisperModel, **kwargs)


class _WhisperEngine:
    """Buffers PCM16 audio and transcribes segments on a worker thread.

    Faster-Whisper has no live-streaming mode, so the stream is cut into
    SEGMENT_SECONDS chunks and each is transcribed (emitted as a final). The
    model is loaded on the worker thread (not in connect()) because the first
    load can download hundreds of MB and take tens of seconds — doing it here
    keeps connect() fast so START does not time out. The audio backlog is
    capped (drop-oldest) so slow CPU transcription cannot exhaust memory, and a
    trailing chunk shorter than a full segment is flushed after a short silence
    so the last words are not lost."""

    def __init__(
        self,
        whisper_model_cls,
        *,
        model: str,
        device: str,
        sample_rate: int,
        language: str,
        on_partial: TextCb,
        on_final: TextCb,
        on_error: TextCb,
    ) -> None:
        import numpy as np

        self._np = np
        self._model_cls = whisper_model_cls
        self._model_name = model
        self._device = device
        self._sample_rate = sample_rate
        self._language = (language or "").lower() or None
        self._on_final = on_final
        self._on_error = on_error
        self._model = None  # loaded lazily on the worker thread
        self._segment_bytes = int(sample_rate * SEGMENT_SECONDS) * 2  # PCM16 = 2 B/sample
        self._max_bytes = int(sample_rate * MAX_BUFFER_SECONDS) * 2
        self._buffer = bytearray()
        self._lock = threading.Lock()
        self._closed = False
        self._last_push = time.monotonic()
        self._thread = threading.Thread(
            target=self._run, name="faster-whisper", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def push(self, chunk: bytes) -> None:
        if self._closed:
            return
        with self._lock:
            self._buffer.extend(chunk)
            self._last_push = time.monotonic()
            # backpressure: keep only the most recent MAX_BUFFER_SECONDS of audio
            excess = len(self._buffer) - self._max_bytes
            if excess > 0:
                del self._buffer[:excess]

    def stop(self) -> None:
        self._closed = True

    def _take_segment(self) -> bytes | None:
        with self._lock:
            if len(self._buffer) >= self._segment_bytes:
                segment = bytes(self._buffer[: self._segment_bytes])
                del self._buffer[: self._segment_bytes]
                return segment
            # trailing audio after a silence: flush it even if shorter
            idle = time.monotonic() - self._last_push
            if self._buffer and idle >= SEGMENT_SECONDS:
                segment = bytes(self._buffer)
                self._buffer.clear()
                return segment
            return None

    def _transcribe(self, segment: bytes) -> None:
        audio = (
            self._np.frombuffer(segment, dtype=self._np.int16).astype("float32") / 32768.0
        )
        segments, _info = self._model.transcribe(audio, language=self._language)
        text = " ".join(seg.text.strip() for seg in segments).strip()
        if text and not self._closed:
            self._on_final(text)

    def _run(self) -> None:
        try:
            self._model = self._model_cls(self._model_name, device=self._device)
        except Exception:
            if not self._closed:
                logger.warning("Caricamento modello Faster-Whisper fallito")
                self._on_error(t("local.whisper_model_load_failed"))
            return
        while not self._closed:
            segment = self._take_segment()
            if segment is None:
                time.sleep(0.1)
                continue
            try:
                self._transcribe(segment)
            except Exception:
                if not self._closed:
                    logger.warning("Trascrizione Faster-Whisper fallita")
                    self._on_error(t("local.whisper_failed"))
