# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""Provider interfaces.

v1 uses a combined realtime provider (audio in → translated text out).
v1.1 also exposes the future split so pipelines like Google Speech → DeepL or
Faster-Whisper → MarianMT can be composed without GUI changes:

- ``SpeechProvider``: audio → source-language text (partial/final events);
- ``TranslationProvider``: source text → translated text;
- ``ComposedRealtimeProvider`` (see composed.py) combines the two and satisfies
  the ``RealtimeTranslationProvider`` interface the pipeline already uses.

The GUI/pipeline depend only on ``RealtimeTranslationProvider``.
"""

from __future__ import annotations

import abc
from collections.abc import Callable
from dataclasses import dataclass

TextCallback = Callable[[str], None]
ErrorCallback = Callable[[str], None]


class ProviderError(Exception):
    """Base for provider errors carrying an operator-readable message (Italian).

    All concrete provider errors (OpenAI, DeepL, Azure, Google, local models)
    subclass this so the service layer can surface their message to the operator
    on START instead of a generic one."""


@dataclass
class ProviderConfig:
    """Non-sensitive provider settings. The API key is fetched from the
    SecretStore by the provider itself and never travels through config files."""

    provider: str = "openai"
    source_language: str = "es"
    target_language: str = "it"
    sample_rate: int = 16000
    channels: int = 1


class TextEventEmitter:
    """Registration and emission of text events (partial/final/error).

    Shared by RealtimeTranslationProvider and SpeechProvider: the semantics of
    the text (already translated vs source language) depend on the subclass. The
    callbacks are invoked from the provider's I/O thread/loop: consumers must
    marshal them onto their own thread.
    """

    def __init__(self) -> None:
        self._partial_callbacks: list[TextCallback] = []
        self._final_callbacks: list[TextCallback] = []
        self._error_callbacks: list[ErrorCallback] = []

    def on_partial_text(self, callback: TextCallback) -> None:
        self._partial_callbacks.append(callback)

    def on_final_text(self, callback: TextCallback) -> None:
        self._final_callbacks.append(callback)

    def on_error(self, callback: ErrorCallback) -> None:
        self._error_callbacks.append(callback)

    def _emit_partial(self, text: str) -> None:
        for callback in self._partial_callbacks:
            callback(text)

    def _emit_final(self, text: str) -> None:
        for callback in self._final_callbacks:
            callback(text)

    def _emit_error(self, message: str) -> None:
        for callback in self._error_callbacks:
            callback(message)


class RealtimeTranslationProvider(TextEventEmitter, abc.ABC):
    """Streams audio chunks to a provider and emits TRANSLATED text events."""

    @abc.abstractmethod
    async def connect(self, config: ProviderConfig) -> None: ...

    @abc.abstractmethod
    async def send_audio(self, chunk: bytes) -> None: ...

    @abc.abstractmethod
    async def close(self) -> None: ...

    def request_close(self) -> None:
        """Synchronous hint that a close is imminent (called from the stop
        thread before the async close() is scheduled).

        Lets a provider suppress reconnection/error emission for an *intentional*
        stop even before close() runs on the event loop. Default: no-op.
        """
        return None


class SpeechProvider(TextEventEmitter, abc.ABC):
    """Streams audio chunks and emits SOURCE-language text events
    (partial/final). Does not translate: translation is the job of the
    TranslationProvider."""

    @abc.abstractmethod
    async def connect(self, config: ProviderConfig) -> None: ...

    @abc.abstractmethod
    async def send_audio(self, chunk: bytes) -> None: ...

    @abc.abstractmethod
    async def close(self) -> None: ...


class TranslationProvider(abc.ABC):
    """Translates text from the source language to the target language.

    connect()/close() have empty defaults: a stateless translator (e.g. a
    REST call per sentence) need not implement them.
    """

    async def connect(self, config: ProviderConfig) -> None:
        return None

    @abc.abstractmethod
    async def translate(self, text: str) -> str: ...

    async def close(self) -> None:
        return None
