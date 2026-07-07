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

# Silence-aware segmentation: cut at speech pauses instead of at a fixed
# interval, so words are no longer bisected at segment boundaries (the main
# source of lost words in live use).
MIN_SEGMENT_SECONDS = 1.0  # Whisper hallucinates on sub-second clips
MAX_SEGMENT_SECONDS = 6.0  # hard latency cap during unbroken speech
SILENCE_WINDOW_SECONDS = 0.4  # inter-phrase pause length that triggers a cut
FRAME_SECONDS = 0.03  # RMS frame: 480 samples / 960 bytes at 16 kHz (sample-aligned)
SILENCE_RMS = 0.01  # ~ -40 dBFS on normalized PCM16
IDLE_FLUSH_SECONDS = 1.0  # capture stalled/stopped: flush the trailing audio fast
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
    segments and each is transcribed (emitted as a final). Segmentation is
    silence-aware: a segment ends at a speech pause (SILENCE_WINDOW_SECONDS of
    frames under SILENCE_RMS), so words are not bisected at boundaries; during
    unbroken speech a hard cap (MAX_SEGMENT_SECONDS) cuts at the quietest
    recent frame. All-silent segments are skipped (Whisper hallucinates text on
    silence). The model is loaded on the worker thread (not in connect())
    because the first load can download hundreds of MB and take tens of
    seconds — doing it here keeps connect() fast so START does not time out.
    The audio backlog is capped (drop-oldest) so slow CPU transcription cannot
    exhaust memory, and trailing audio is flushed once the capture goes idle so
    the last words are not lost."""

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
        # PCM16 = 2 B/sample; every cut is a multiple of _frame_bytes, so it is
        # always sample-aligned
        self._frame_bytes = int(sample_rate * FRAME_SECONDS) * 2
        self._frame_samples = int(sample_rate * FRAME_SECONDS)
        self._min_segment_bytes = int(sample_rate * MIN_SEGMENT_SECONDS) * 2
        self._max_segment_bytes = int(sample_rate * MAX_SEGMENT_SECONDS) * 2
        self._silence_frames = round(SILENCE_WINDOW_SECONDS / FRAME_SECONDS)
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

    def _frame_rms(self, data: bytes):
        """Per-frame normalized RMS (0..1) over the full 30 ms frames of ``data``."""
        np = self._np
        n = len(data) // self._frame_bytes
        if n == 0:
            return np.zeros(0, dtype="float32")
        samples = np.frombuffer(data[: n * self._frame_bytes], dtype="<i2")
        frames = samples.reshape(n, self._frame_samples).astype("float32")
        return np.sqrt(np.mean(frames * frames, axis=1)) / 32768.0

    def _is_silent(self, segment: bytes) -> bool:
        """True when no frame of the segment reaches speech level (gates the
        'subtitles by...' style hallucinations Whisper produces on silence)."""
        rms = self._frame_rms(segment)
        return rms.size == 0 or float(rms.max()) < SILENCE_RMS

    def _take_segment(self) -> bytes | None:
        # everything under the lock: push() deletes from the buffer front, so
        # no index may be computed outside it (the RMS scan on <=6 s of audio
        # costs microseconds)
        with self._lock:
            np = self._np
            if len(self._buffer) >= self._min_segment_bytes:
                rms = self._frame_rms(bytes(self._buffer))
                silent = rms < SILENCE_RMS
                # pause cut: first window of SILENCE_WINDOW_SECONDS fully silent
                # frames whose start honors the minimum segment length; keep the
                # trailing pause in the segment (helps Whisper close the phrase)
                start = -(-self._min_segment_bytes // self._frame_bytes)  # ceil
                window = self._silence_frames
                if silent.size >= start + window:
                    runs = np.convolve(
                        silent.astype("int32"), np.ones(window, dtype="int32"), "valid"
                    )
                    candidates = np.nonzero(runs[start:] == window)[0]
                    if candidates.size:
                        cut = (start + int(candidates[0]) + window) * self._frame_bytes
                        segment = bytes(self._buffer[:cut])
                        del self._buffer[:cut]
                        return segment
                # hard cap during unbroken speech: cut at the quietest frame of
                # the last second before the cap (the closest thing to a pause).
                # The LAST minimal frame is chosen so uniform audio cuts at the
                # cap itself, not one second early.
                if len(self._buffer) >= self._max_segment_bytes:
                    max_frames = self._max_segment_bytes // self._frame_bytes
                    lookback = round(1.0 / FRAME_SECONDS)
                    tail = rms[max_frames - lookback : max_frames]
                    j = (max_frames - 1) - int(np.argmin(tail[::-1]))
                    cut = (j + 1) * self._frame_bytes
                    segment = bytes(self._buffer[:cut])
                    del self._buffer[:cut]
                    return segment
            # capture stalled/stopped: flush the trailing audio quickly (while
            # capture runs, push() delivers silent PCM continuously, so idle
            # means the stream stopped — speaker pauses are the cut above)
            idle = time.monotonic() - self._last_push
            if self._buffer and idle >= IDLE_FLUSH_SECONDS:
                segment = bytes(self._buffer)
                self._buffer.clear()
                return segment
            return None

    def _transcribe(self, segment: bytes) -> None:
        audio = (
            self._np.frombuffer(segment, dtype=self._np.int16).astype("float32") / 32768.0
        )
        # live-tuned decoding: greedy beam and no temperature fallback keep CPU
        # cost ~realtime (fewer backlog drops); conditioning off + thresholds +
        # VAD suppress the repetition/hallucination failure modes of small
        # models on chunked live audio
        segments, _info = self._model.transcribe(
            audio,
            language=self._language,
            beam_size=1,
            temperature=0.0,
            condition_on_previous_text=False,
            no_speech_threshold=0.5,
            log_prob_threshold=-0.7,
            vad_filter=True,
            vad_parameters={
                "threshold": 0.4,
                "min_silence_duration_ms": 500,
                "speech_pad_ms": 200,
                "min_speech_duration_ms": 250,
            },
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        if text and not self._closed:
            self._on_final(text)

    def _run(self) -> None:
        try:
            self._model = self._model_cls(self._model_name, device=self._device)
        except Exception:
            if not self._closed:
                # full traceback: "missing cublas64_12.dll" is undiagnosable
                # otherwise. On CUDA the cause is almost always GPU
                # components/drivers, so the message is actionable.
                logger.warning(
                    "Caricamento modello Faster-Whisper fallito (device=%s, model=%s)",
                    self._device,
                    self._model_name,
                    exc_info=True,
                )
                key = (
                    "local.whisper_gpu_load_failed"
                    if self._device == "cuda"
                    else "local.whisper_model_load_failed"
                )
                self._on_error(t(key))
            return
        while not self._closed:
            segment = self._take_segment()
            if segment is None:
                time.sleep(0.1)
                continue
            if self._is_silent(segment):
                continue  # nothing to transcribe (also avoids hallucinated text)
            try:
                self._transcribe(segment)
            except Exception:
                if not self._closed:
                    logger.warning("Trascrizione Faster-Whisper fallita")
                    self._on_error(t("local.whisper_failed"))
