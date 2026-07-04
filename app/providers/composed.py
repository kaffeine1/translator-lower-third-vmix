# Translator Lower Third for vMix
# Autore: Michele Dipace <michele.dipace@kaffeine.net>
"""Composizione SpeechProvider + TranslationProvider (v1.1).

ComposedRealtimeProvider unisce un provider di riconoscimento vocale (audio →
testo sorgente) e un provider di traduzione (testo sorgente → testo tradotto)
dietro l'interfaccia RealtimeTranslationProvider già usata dalla pipeline.
Così pipeline future (Google Speech → DeepL, Faster-Whisper → MarianMT…) non
richiedono modifiche a GUI o servizi.

Include implementazioni finte per test/demo senza API.
"""

from __future__ import annotations

import asyncio
import logging

from app.providers.base import (
    ProviderConfig,
    RealtimeTranslationProvider,
    SpeechProvider,
    TranslationProvider,
)

logger = logging.getLogger("app.providers.composed")


class ComposedRealtimeProvider(RealtimeTranslationProvider):
    """Adatta (SpeechProvider, TranslationProvider) all'interfaccia combinata.

    Il testo sorgente riconosciuto viene tradotto e riemesso come evento
    tradotto. Un contatore di sequenza scarta le traduzioni di parziali ormai
    superati (o invalidati da un finale), evitando sfarfallii da risposte in
    ritardo/fuori ordine dei traduttori reali."""

    def __init__(self, speech: SpeechProvider, translator: TranslationProvider) -> None:
        super().__init__()
        self._speech = speech
        self._translator = translator
        self._seq = 0
        self._closed = False
        self._loop: asyncio.AbstractEventLoop | None = None
        speech.on_partial_text(self._on_source_partial)
        speech.on_final_text(self._on_source_final)
        speech.on_error(self._emit_error)

    async def connect(self, config: ProviderConfig) -> None:
        self._closed = False
        # gli SDK vocali (Azure, Google) invocano le callback su thread propri:
        # cattura il loop qui per poterci pianificare le traduzioni in modo
        # thread-safe da qualunque thread
        self._loop = asyncio.get_running_loop()
        await self._translator.connect(config)
        await self._speech.connect(config)

    async def send_audio(self, chunk: bytes) -> None:
        await self._speech.send_audio(chunk)

    async def close(self) -> None:
        self._closed = True
        await self._speech.close()
        await self._translator.close()

    # -- callback dal SpeechProvider (può arrivare da un thread SDK) -----------

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
            # callback già sul loop (fake, provider asyncio): via immediata
            loop.create_task(coro)
        else:
            # callback da un thread SDK (Azure, Google): pianifica sul loop
            try:
                asyncio.run_coroutine_threadsafe(coro, loop)
            except RuntimeError:
                coro.close()

    def _on_source_partial(self, text: str) -> None:
        self._seq += 1
        seq = self._seq
        self._schedule(self._translate_partial(text, seq))

    def _on_source_final(self, text: str) -> None:
        # un finale invalida i parziali pendenti ma la sua traduzione va
        # sempre emessa
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
        try:
            translated = await self._translator.translate(text)
        except Exception:
            logger.exception("Traduzione finale fallita")
            self._emit_error("Errore di traduzione")
            return
        if not self._closed and translated:
            self._emit_final(translated)


# --------------------------------------------------------------------------- #
# Implementazioni finte (nessuna rete)
# --------------------------------------------------------------------------- #

# Parlato sorgente simulato (spagnolo), da tradurre in italiano.
DEMO_SPEECH_SCRIPT: list[tuple[str, str]] = [
    ("partial", "Bienvenidos"),
    ("partial", "Bienvenidos a este"),
    ("final", "Bienvenidos a este evento en vivo."),
    ("partial", "Hoy hablamos"),
    ("final", "Hoy hablamos de tecnología e innovación."),
    ("final", "Gracias a todos por la participación."),
]

# Traduzione demo spagnolo → italiano per le frasi dello script.
DEMO_TRANSLATION_MAP: dict[str, str] = {
    "Bienvenidos": "Benvenuti",
    "Bienvenidos a este": "Benvenuti a questo",
    "Bienvenidos a este evento en vivo.": "Benvenuti a questo evento dal vivo.",
    "Hoy hablamos": "Oggi parliamo",
    "Hoy hablamos de tecnología e innovación.": "Oggi parliamo di tecnologia e innovazione.",
    "Gracias a todos por la participación.": "Grazie a tutti per la partecipazione.",
}


class FakeSpeechProvider(SpeechProvider):
    """Emette testo sorgente scriptato su timeline, ignorando l'audio."""

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
    """Traduttore finto: usa una mappa (default: identità con marcatore)."""

    def __init__(self, mapping: dict[str, str] | None = None, delay: float = 0.0) -> None:
        self._mapping = mapping if mapping is not None else DEMO_TRANSLATION_MAP
        self._delay = delay

    async def translate(self, text: str) -> str:
        if self._delay:
            await asyncio.sleep(self._delay)
        return self._mapping.get(text, text)


def make_demo_composed_provider() -> ComposedRealtimeProvider:
    """Provider demo che dimostra la pipeline speech+traduzione separati."""
    return ComposedRealtimeProvider(FakeSpeechProvider(), FakeTranslationTextProvider())
