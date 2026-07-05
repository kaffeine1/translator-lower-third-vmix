# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""LocalMarianTranslationProvider — local (offline) text translation (v1.3).

A TranslationProvider: source text -> translated text, run locally with a
MarianMT model (Hugging Face ``transformers``). No cloud, no API cost. Combine
it with a SpeechProvider (local Faster-Whisper or a cloud one) inside a
ComposedRealtimeProvider.

All translation-model logic lives here; the model "translator" is injectable so
tests run with a fake (no model download, no heavy dependency). The real model
needs the optional ``transformers`` + ``torch`` packages (see
requirements-optional.txt). The model name defaults to the Helsinki-NLP OPUS-MT
pair for the configured languages and can be overridden.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from app.i18n import t
from app.providers.base import ProviderConfig, ProviderError, TranslationProvider

logger = logging.getLogger("app.providers.local_translate")

# a callable that, given a model name, returns fn(text) -> translated text
TranslatorFactory = Callable[[str], "Callable[[str], str]"]


class LocalTranslationError(ProviderError):
    """Local translation error with an operator-readable message (Italian)."""


def default_model_name(source: str, target: str) -> str:
    """OPUS-MT model for the language pair, e.g. es->it -> opus-mt-es-it."""
    return f"Helsinki-NLP/opus-mt-{(source or '').lower()}-{(target or '').lower()}"


class LocalMarianTranslationProvider(TranslationProvider):
    def __init__(
        self,
        model_name: str | None = None,
        translator_factory: TranslatorFactory | None = None,
    ) -> None:
        self._model_name = model_name
        self._translator_factory = translator_factory or _make_real_translator
        self._translate_fn: Callable[[str], str] | None = None
        self._resolved_model = ""

    async def connect(self, config: ProviderConfig) -> None:
        # keep connect() fast: only resolve the model name. The model is built
        # lazily on the first translate() call, off the event-loop thread, so
        # START does not block or time out on a slow first-time model load.
        self._resolved_model = self._model_name or default_model_name(
            config.source_language, config.target_language
        )
        self._translate_fn = None

    async def translate(self, text: str) -> str:
        if not text.strip():
            return ""
        try:
            # run the (blocking) model build+inference off the asyncio loop
            # thread: otherwise it would stall audio forwarding to the recognizer
            return await asyncio.to_thread(self._translate_blocking, text)
        except LocalTranslationError:
            raise
        except Exception:
            logger.warning("Traduzione locale fallita")
            raise LocalTranslationError(t("local.translate_failed")) from None

    def _translate_blocking(self, text: str) -> str:
        if self._translate_fn is None:
            self._translate_fn = self._translator_factory(self._resolved_model)
        return self._translate_fn(text)

    async def close(self) -> None:
        self._translate_fn = None


def _make_real_translator(model_name: str) -> Callable[[str], str]:
    try:
        from transformers import pipeline
    except ImportError:
        raise LocalTranslationError(t("local.transformers_not_installed")) from None
    translator = pipeline("translation", model=model_name)

    def translate(text: str) -> str:
        result = translator(text)
        # transformers returns [{"translation_text": "..."}]
        return result[0]["translation_text"]

    return translate
