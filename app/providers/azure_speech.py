# Translator Lower Third for vMix
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""AzureSpeechProvider — Microsoft cloud speech recognition (v1.2).

It is a SpeechProvider: audio → source text (partial/final). It must be combined
with a TranslationProvider (e.g. DeepL) inside a ComposedRealtimeProvider.

All Azure-specific logic lives here. The key (and the region) are read from
secure storage and never appear in the logs. The recognition "engine" is
injectable: tests use a fake engine, with no SDK or network. The real engine
requires the optional package ``azure-cognitiveservices-speech`` (see
requirements-optional.txt), not included in the base package.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from app.config.secrets import SecretStore
from app.providers.base import ProviderConfig, SpeechProvider

logger = logging.getLogger("app.providers.azure")

# Azure language codes (BCP-47)
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


class AzureSpeechError(Exception):
    """Azure Speech error with an operator-readable message (Italian)."""


TextCb = Callable[[str], None]
# engine signature: factory(**opts) -> object with start()/push(bytes)/stop()
EngineFactory = Callable[..., "object"]


class AzureSpeechProvider(SpeechProvider):
    def __init__(
        self,
        secret_store: SecretStore | None,
        provider_name: str = "azure",
        region: str | None = None,
        engine_factory: EngineFactory | None = None,
    ) -> None:
        super().__init__()
        self._secret_store = secret_store
        self._provider_name = provider_name
        self._region = region
        self._engine_factory = engine_factory or _make_real_engine
        self._engine: object | None = None

    async def connect(self, config: ProviderConfig) -> None:
        key = self._secret_store.get_api_key(self._provider_name) if self._secret_store else None
        if not key:
            raise AzureSpeechError(
                "Nessuna chiave Azure Speech salvata. Inseriscila nelle Impostazioni."
            )
        region = self._region
        if not region and self._secret_store is not None:
            region = self._secret_store.get_api_key("azure-region")
        if not region:
            raise AzureSpeechError(
                "Regione Azure non impostata (es. westeurope). Inseriscila nelle Impostazioni."
            )
        self._engine = self._engine_factory(
            key=key,
            region=region,
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
                logger.exception("Errore fermando Azure Speech")


def _make_real_engine(**kwargs) -> object:
    try:
        import azure.cognitiveservices.speech as speechsdk
    except ImportError:
        raise AzureSpeechError(
            "Modulo Azure Speech non installato. Installa "
            "'azure-cognitiveservices-speech' per usare questo provider."
        ) from None
    return _AzureEngine(speechsdk, **kwargs)


class _AzureEngine:
    """Adapter over the Azure SDK. SDK callbacks arrive on their own threads: the
    ComposedRealtimeProvider forwards them to the asyncio loop in a thread-safe way."""

    def __init__(
        self,
        speechsdk,
        *,
        key: str,
        region: str,
        language: str,
        sample_rate: int,
        on_partial: TextCb,
        on_final: TextCb,
        on_error: TextCb,
    ) -> None:
        speech_config = speechsdk.SpeechConfig(subscription=key, region=region)
        speech_config.speech_recognition_language = language
        audio_format = speechsdk.audio.AudioStreamFormat(
            samples_per_second=sample_rate, bits_per_sample=16, channels=1
        )
        self._push = speechsdk.audio.PushAudioInputStream(stream_format=audio_format)
        audio_config = speechsdk.audio.AudioConfig(stream=self._push)
        self._recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config, audio_config=audio_config
        )
        self._recognizer.recognizing.connect(
            lambda evt: on_partial(evt.result.text) if evt.result.text else None
        )
        self._recognizer.recognized.connect(
            lambda evt: on_final(evt.result.text) if evt.result.text else None
        )
        self._recognizer.canceled.connect(
            lambda evt: on_error("Connessione persa con Azure Speech")
        )

    def start(self) -> None:
        self._recognizer.start_continuous_recognition()

    def push(self, chunk: bytes) -> None:
        self._push.write(chunk)

    def stop(self) -> None:
        try:
            self._recognizer.stop_continuous_recognition()
        finally:
            self._push.close()
