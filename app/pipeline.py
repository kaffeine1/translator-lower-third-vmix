# Translator Lower Third for vMix
# Autore: Michele Dipace <michele.dipace@kaffeine.net>
"""TranslationPipeline — collega provider → formatter → uscite.

Ciclo di vita gestito qui, fuori dalla GUI:
- un thread con event loop asyncio ospita il provider (connect/send_audio/close);
- gli eventi di testo del provider (thread del loop) alimentano il
  SubtitleFormatter;
- un thread "tick" chiama formatter.tick() ~ogni 250 ms (parziali stabili,
  pulizia dopo silenzio);
- il callback publish del formatter è velocissimo: accoda il testo. Un thread
  "output" consuma la coda e lo invia all'uscita (vMix), che può bloccare.

STOP ferma e unisce tutti i thread: nessun thread appeso. L'audio è opzionale:
se la cattura fallisce, la pipeline continua (utile per la demo del provider
finto senza microfono).
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
from collections.abc import Callable

from app.audio.input import AudioInput
from app.config.models import AppConfig
from app.providers.base import ProviderConfig, RealtimeTranslationProvider
from app.subtitles.formatter import SubtitleFormatter

logger = logging.getLogger("app.pipeline")

TICK_INTERVAL_S = 0.25
_OUTPUT_SENTINEL = object()

TextSink = Callable[[str], None]
ErrorSink = Callable[[str], None]


class TranslationPipeline:
    def __init__(
        self,
        provider: RealtimeTranslationProvider,
        config: AppConfig,
        on_subtitle: TextSink,
        output_publish: TextSink,
        on_error: ErrorSink | None = None,
        audio_input: AudioInput | None = None,
    ) -> None:
        self._provider = provider
        self._config = config
        self._on_subtitle = on_subtitle
        self._output_publish = output_publish
        self._on_error = on_error
        self._audio = audio_input

        self._formatter = SubtitleFormatter(config.subtitles, self._on_formatter_publish)
        self._output_queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._tick_thread: threading.Thread | None = None
        self._output_thread: threading.Thread | None = None
        self._started = False

    # ------------------------------------------------------------------ start

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._stop_event.clear()

        self._output_thread = threading.Thread(
            target=self._output_worker, name="pipeline-output", daemon=True
        )
        self._output_thread.start()

        self._tick_thread = threading.Thread(
            target=self._tick_worker, name="pipeline-tick", daemon=True
        )
        self._tick_thread.start()

        self._provider.on_partial_text(self._formatter.feed_partial)
        self._provider.on_final_text(self._formatter.feed_final)
        self._provider.on_error(self._handle_error)

        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._run_loop, name="pipeline-provider", daemon=True
        )
        self._loop_thread.start()

        provider_config = ProviderConfig(
            provider=self._config.provider,
            source_language=self._config.source_language,
            target_language=self._config.target_language,
            sample_rate=self._config.audio.sample_rate,
            channels=self._config.audio.channels,
        )
        future = asyncio.run_coroutine_threadsafe(
            self._provider.connect(provider_config), self._loop
        )
        future.result(timeout=10)

        self._start_audio_optional()

    def _start_audio_optional(self) -> None:
        if self._audio is None:
            return
        try:
            self._audio.start(
                self._config.audio.device_id,
                sample_rate=self._config.audio.sample_rate,
                channels=self._config.audio.channels,
                on_chunk=self._forward_audio,
            )
        except Exception as exc:
            # la demo del provider finto non ha bisogno dell'audio: si prosegue
            logger.warning("Cattura audio non avviata: %s", type(exc).__name__)

    def _forward_audio(self, chunk: bytes) -> None:
        loop = self._loop
        if loop is None or self._stop_event.is_set():
            return
        asyncio.run_coroutine_threadsafe(self._provider.send_audio(chunk), loop)

    # ------------------------------------------------------------------ stop

    def stop(self) -> None:
        if not self._started:
            return
        self._stop_event.set()

        if self._audio is not None:
            try:
                self._audio.stop()
            except Exception:
                logger.exception("Errore fermando la cattura audio")

        if self._loop is not None:
            try:
                asyncio.run_coroutine_threadsafe(
                    self._provider.close(), self._loop
                ).result(timeout=5)
            except Exception:
                logger.exception("Errore chiudendo il provider")
            self._loop.call_soon_threadsafe(self._loop.stop)

        if self._loop_thread is not None:
            self._loop_thread.join(timeout=5)
        if self._loop is not None:
            self._loop.close()
            self._loop = None

        if self._tick_thread is not None:
            self._tick_thread.join(timeout=5)

        self._output_queue.put(_OUTPUT_SENTINEL)
        if self._output_thread is not None:
            self._output_thread.join(timeout=5)

        self._formatter.reset()
        self._started = False

    # ------------------------------------------------------------------ worker

    def _run_loop(self) -> None:
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_forever()
        finally:
            # completa i task residui (es. cancellazioni) prima di chiudere
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()
            if pending:
                self._loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )

    def _tick_worker(self) -> None:
        while not self._stop_event.wait(TICK_INTERVAL_S):
            try:
                self._formatter.tick()
            except Exception:
                logger.exception("Errore nel tick del formatter")

    def _output_worker(self) -> None:
        while True:
            item = self._output_queue.get()
            if item is _OUTPUT_SENTINEL:
                return
            try:
                self._output_publish(item)
            except Exception:
                logger.exception("Errore inviando il sottotitolo all'uscita")

    # ------------------------------------------------------------------ sink

    def _on_formatter_publish(self, text: str) -> None:
        # invocato dal thread provider (finale) o tick (parziale): solo accoda
        self._output_queue.put(text)
        self._on_subtitle(text)

    def _handle_error(self, message: str) -> None:
        logger.warning("Errore provider: %s", message)
        if self._on_error is not None:
            self._on_error(message)
