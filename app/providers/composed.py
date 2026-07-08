# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""Composition of SpeechProvider + TranslationProvider (v1.1).

ComposedRealtimeProvider combines a speech recognition provider (audio →
source text) and a translation provider (source text → translated text)
behind the RealtimeTranslationProvider interface already used by the pipeline.
This way future pipelines (Google Speech → DeepL, Faster-Whisper → MarianMT…)
require no changes to the GUI or services.

Includes fake implementations for tests/demos without APIs.
"""

from __future__ import annotations

import asyncio
import logging

from app.i18n import t
from app.providers.base import (
    ProviderConfig,
    ProviderError,
    RealtimeTranslationProvider,
    SpeechProvider,
    TranslationProvider,
)

logger = logging.getLogger("app.providers.composed")


class ComposedRealtimeProvider(RealtimeTranslationProvider):
    """Adapts (SpeechProvider, TranslationProvider) to the combined interface.

    The recognized source text is translated and re-emitted as a translated
    event. A sequence counter discards translations of partials that are now
    outdated (or invalidated by a final), avoiding flicker from late/out-of-order
    responses from real translators."""

    def __init__(self, speech: SpeechProvider, translator: TranslationProvider) -> None:
        super().__init__()
        self._speech = speech
        self._translator = translator
        self._seq = 0
        self._closed = False
        self._loop: asyncio.AbstractEventLoop | None = None
        # finals must reach the air in speech order: without this, two final
        # translations in flight can complete out of order (the shorter text
        # translates faster) and captions swap on air. asyncio.Lock wakes
        # waiters FIFO, so serializing here preserves the arrival order.
        self._final_lock = asyncio.Lock()
        # same source/target language = captioning without translation: the
        # recognized text goes on air as-is (e.g. Italian speech -> Italian
        # subtitles). Decided in connect() from the configured languages.
        self._passthrough = False
        # streaming speech providers emit partials at ~1 Hz; the committed
        # prefix is often unchanged between ticks. Skip identical partials so a
        # translator (MarianMT CPU / DeepL cost) is not re-run for nothing.
        self._last_partial_src = ""
        speech.on_partial_text(self._on_source_partial)
        speech.on_final_text(self._on_source_final)
        speech.on_error(self._emit_error)

    async def connect(self, config: ProviderConfig) -> None:
        self._closed = False
        # speech SDKs (Azure, Google) invoke callbacks on their own threads:
        # capture the loop here so translations can be scheduled on it in a
        # thread-safe way from any thread
        self._loop = asyncio.get_running_loop()
        source = (config.source_language or "").strip().lower()
        target = (config.target_language or "").strip().lower()
        self._passthrough = bool(source) and source == target
        if not self._passthrough:  # captioning-only needs no translator
            await self._translator.connect(config)
        await self._speech.connect(config)

    async def send_audio(self, chunk: bytes) -> None:
        await self._speech.send_audio(chunk)

    async def close(self) -> None:
        self._closed = True
        await self._speech.close()
        if not self._passthrough:  # never connected in captioning-only mode
            await self._translator.close()

    # -- callbacks from the SpeechProvider (may arrive from an SDK thread) -----

    def _schedule(self, coro) -> None:
        loop = self._loop
        if loop is None or self._closed:
            coro.close()
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            # callback already on the loop (fake, asyncio provider): dispatch immediately
            loop.create_task(coro)
        else:
            # callback from an SDK thread (Azure, Google): schedule onto the loop
            try:
                asyncio.run_coroutine_threadsafe(coro, loop)
            except RuntimeError:
                coro.close()

    def _on_source_partial(self, text: str) -> None:
        if text == self._last_partial_src:  # unchanged committed prefix: skip
            return
        self._last_partial_src = text
        if self._passthrough:
            if not self._closed and text:
                self._emit_partial(text)  # emitters are thread-safe downstream
            return
        self._seq += 1
        seq = self._seq
        self._schedule(self._translate_partial(text, seq))

    def _on_source_final(self, text: str) -> None:
        self._last_partial_src = ""  # next caption's partials start fresh
        if self._passthrough:
            if not self._closed and text:
                self._emit_final(text)
            return
        # a final invalidates pending partials but its translation must
        # always be emitted
        self._seq += 1
        self._schedule(self._translate_final(text))

    async def _translate_partial(self, text: str, seq: int) -> None:
        try:
            translated = await self._translator.translate(text)
        except Exception:
            logger.exception("Traduzione parziale fallita")
            return
        if not self._closed and translated and seq == self._seq:
            self._emit_partial(translated)

    async def _translate_final(self, text: str) -> None:
        async with self._final_lock:  # keep finals in speech order (see __init__)
            try:
                translated = await self._translator.translate(text)
            except ProviderError as exc:
                # the translator already has an operator-readable, actionable
                # message (e.g. "translation model not downloaded") — surface it
                # instead of the generic fallback
                logger.exception("Traduzione finale fallita")
                self._emit_error(str(exc) or t("provider.translate_failed"))
                return
            except Exception:
                logger.exception("Traduzione finale fallita")
                self._emit_error(t("provider.translate_failed"))
                return
            if not self._closed and translated:
                self._emit_final(translated)


# --------------------------------------------------------------------------- #
# Fake implementations (no network)
# --------------------------------------------------------------------------- #

# Simulated source speech (Spanish), to be translated into Italian.
DEMO_SPEECH_SCRIPT: list[tuple[str, str]] = [
    ("partial", "Bienvenidos"),
    ("partial", "Bienvenidos a este"),
    ("final", "Bienvenidos a este evento en vivo."),
    ("partial", "Hoy hablamos"),
    ("final", "Hoy hablamos de tecnología e innovación."),
    ("final", "Gracias a todos por la participación."),
]

# Demo Spanish → Italian translation for the script phrases.
DEMO_TRANSLATION_MAP: dict[str, str] = {
    "Bienvenidos": "Benvenuti",
    "Bienvenidos a este": "Benvenuti a questo",
    "Bienvenidos a este evento en vivo.": "Benvenuti a questo evento dal vivo.",
    "Hoy hablamos": "Oggi parliamo",
    "Hoy hablamos de tecnología e innovación.": "Oggi parliamo di tecnologia e innovazione.",
    "Gracias a todos por la participación.": "Grazie a tutti per la partecipazione.",
}


class FakeSpeechProvider(SpeechProvider):
    """Emits scripted source text on a timeline, ignoring the audio."""

    def __init__(
        self,
        script: list[tuple[str, str]] | None = None,
        step_delay: float = 0.8,
        loop: bool = True,
    ) -> None:
        super().__init__()
        self._script = script if script is not None else DEMO_SPEECH_SCRIPT
        self._step_delay = step_delay
        self._loop = loop
        self._task: asyncio.Task | None = None
        self._closed = False

    async def connect(self, config: ProviderConfig) -> None:
        self._closed = False
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            while not self._closed:
                for kind, text in self._script:
                    if self._closed:
                        return
                    await asyncio.sleep(self._step_delay)
                    if kind == "partial":
                        self._emit_partial(text)
                    else:
                        self._emit_final(text)
                if not self._loop:
                    return
        except asyncio.CancelledError:
            raise

    async def send_audio(self, chunk: bytes) -> None:
        return None

    async def close(self) -> None:
        self._closed = True
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


class FakeTranslationTextProvider(TranslationProvider):
    """Fake translator: uses a map (default: identity with marker)."""

    def __init__(self, mapping: dict[str, str] | None = None, delay: float = 0.0) -> None:
        self._mapping = mapping if mapping is not None else DEMO_TRANSLATION_MAP
        self._delay = delay

    async def translate(self, text: str) -> str:
        if self._delay:
            await asyncio.sleep(self._delay)
        return self._mapping.get(text, text)


def make_demo_composed_provider() -> ComposedRealtimeProvider:
    """Demo provider that showcases the separated speech+translation pipeline."""
    return ComposedRealtimeProvider(FakeSpeechProvider(), FakeTranslationTextProvider())
