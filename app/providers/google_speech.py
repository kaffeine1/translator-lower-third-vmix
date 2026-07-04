# Translator Lower Third for vMix
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""GoogleSpeechProvider — Google cloud speech recognition (v1.2).

SpeechProvider: audio → source text (partial/final), to be combined with a
TranslationProvider (e.g. DeepL) inside a ComposedRealtimeProvider.

Google logic isolated here. The credentials (path to the service account JSON
file) are read from secure storage and do not appear in the logs. The streaming
engine is injectable: tests use a fake engine with no SDK or network. The
real engine requires the optional package ``google-cloud-speech`` (see
requirements-optional.txt).
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable

from app.config.secrets import SecretStore
from app.i18n import t
from app.providers.base import ProviderConfig, SpeechProvider

logger = logging.getLogger("app.providers.google")

_BCP47 = {
    "es": "es-ES",
    "it": "it-IT",
    "en": "en-US",
    "fr": "fr-FR",
    "pt": "pt-PT",
    "de": "de-DE",
}


def _lang(code: str) -> str:
    code = (code or "").lower()
    if code in _BCP47:
        return _BCP47[code]
    return f"{code}-{code.upper()}" if code else "en-US"


class GoogleSpeechError(Exception):
    """Google Speech error with an operator-readable message (Italian)."""


TextCb = Callable[[str], None]
EngineFactory = Callable[..., "object"]


class GoogleSpeechProvider(SpeechProvider):
    def __init__(
        self,
        secret_store: SecretStore | None,
        provider_name: str = "google",
        engine_factory: EngineFactory | None = None,
    ) -> None:
        super().__init__()
        self._secret_store = secret_store
        self._provider_name = provider_name
        self._engine_factory = engine_factory or _make_real_engine
        self._engine: object | None = None

    async def connect(self, config: ProviderConfig) -> None:
        # "google" holds the path to the credentials file (service account)
        credentials = (
            self._secret_store.get_api_key(self._provider_name)
            if self._secret_store
            else None
        )
        if not credentials:
            raise GoogleSpeechError(t("google.no_credentials"))
        self._engine = self._engine_factory(
            credentials=credentials,
            language=_lang(config.source_language),
            sample_rate=config.sample_rate,
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
                logger.exception("Errore fermando Google Speech")


def _make_real_engine(**kwargs) -> object:
    try:
        from google.cloud import speech
    except ImportError:
        raise GoogleSpeechError(t("google.module_not_installed")) from None
    return _GoogleEngine(speech, **kwargs)


class _GoogleEngine:
    """Adapter over Google's streaming client. Audio pushed with push()
    feeds a request generator read in a dedicated thread; the responses
    become partial/final events. The callbacks arrive from the reader thread:
    the ComposedRealtimeProvider forwards them to the asyncio loop in a thread-safe way."""

    def __init__(
        self,
        speech,
        *,
        credentials: str,
        language: str,
        sample_rate: int,
        on_partial: TextCb,
        on_final: TextCb,
        on_error: TextCb,
    ) -> None:
        self._speech = speech
        self._on_partial = on_partial
        self._on_final = on_final
        self._on_error = on_error
        self._client = speech.SpeechClient.from_service_account_file(credentials)
        self._config = speech.StreamingRecognitionConfig(
            config=speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=sample_rate,
                language_code=language,
            ),
            interim_results=True,
        )
        self._queue: queue.Queue = queue.Queue()
        self._closed = False
        self._thread = threading.Thread(
            target=self._run, name="google-speech", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def push(self, chunk: bytes) -> None:
        if not self._closed:
            self._queue.put(chunk)

    def stop(self) -> None:
        # Do NOT join here: close() is awaited on the asyncio loop thread and a
        # blocking join would freeze it. The sentinel closes the request
        # generator (and therefore the stream), the daemon thread terminates on
        # its own, and the _closed guard prevents late emissions.
        self._closed = True
        self._queue.put(None)  # unblocks the request generator

    def _requests(self):
        # streaming protocol v2: the FIRST request carries the streaming_config,
        # the subsequent ones the audio
        yield self._speech.StreamingRecognizeRequest(streaming_config=self._config)
        while True:
            chunk = self._queue.get()
            if chunk is None:
                return
            yield self._speech.StreamingRecognizeRequest(audio_content=chunk)

    def _run(self) -> None:
        try:
            responses = self._client.streaming_recognize(requests=self._requests())
            for response in responses:
                if self._closed:
                    return
                for result in response.results:
                    if not result.alternatives:
                        continue
                    text = result.alternatives[0].transcript
                    if not text:
                        continue
                    if result.is_final:
                        self._on_final(text)
                    else:
                        self._on_partial(text)
        except Exception:
            if not self._closed:
                logger.warning("Streaming Google Speech interrotto")
                self._on_error(t("google.connection_lost"))
