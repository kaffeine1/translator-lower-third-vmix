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
import threading
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
        # concurrent first translations must not each build the (heavy) model:
        # the lazy build below runs on to_thread workers, so guard it
        self._build_lock = threading.Lock()

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
            # keep the real traceback in the logs: the operator sees the short
            # Italian message, but without this a model/library failure is
            # undiagnosable (the cause is swallowed by `from None` below)
            logger.warning("Traduzione locale fallita", exc_info=True)
            raise LocalTranslationError(t("local.translate_failed")) from None

    def _translate_blocking(self, text: str) -> str:
        if self._translate_fn is None:
            with self._build_lock:
                if self._translate_fn is None:  # double-checked under the lock
                    self._translate_fn = self._translator_factory(self._resolved_model)
        return self._translate_fn(text)

    async def close(self) -> None:
        self._translate_fn = None


def _local_component_error(exc: Exception) -> str:
    # Distinguish "the component package is genuinely absent" (download it) from
    # "the package is present but its import fails" (a broken environment — point
    # at the log). A ModuleNotFoundError raised from DEEP INSIDE a present package
    # (e.g. torch importing a stdlib module the frozen app did not bundle, so
    # exc.name == "timeit") must NOT read as "not downloaded", or the operator
    # re-downloads for nothing.
    missing = getattr(exc, "name", "") or ""
    absent_component = isinstance(exc, ModuleNotFoundError) and missing in {
        "torch",
        "transformers",
        "sentencepiece",
    }
    key = (
        "local.components_not_downloaded"
        if absent_component
        else "local.components_load_failed"
    )
    return t(key)


def _make_real_translator(model_name: str) -> Callable[[str], str]:
    # transformers 5 removed the "translation" pipeline task, so build the
    # seq2seq model directly — this works on transformers 4.x and 5.x alike.
    # Import torch and transformers separately and log the real error: a bare
    # "not installed" message hides whether the component is missing or present
    # but failing to load (e.g. a DLL load error).
    try:
        import torch  # noqa: F401
    except Exception as exc:
        logger.warning("Import di 'torch' fallito", exc_info=True)
        raise LocalTranslationError(_local_component_error(exc)) from exc
    try:
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
    except Exception as exc:
        logger.warning("Import di 'transformers' fallito", exc_info=True)
        raise LocalTranslationError(_local_component_error(exc)) from exc
    try:
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForSeq2SeqLM.from_pretrained(model_name)
    except Exception as exc:
        # The dominant real-world cause: the OPUS-MT model for this language
        # pair was never downloaded (captioning-only use, source==target, never
        # needs one) and cannot be fetched now (offline). Give an actionable
        # message pointing at the Settings downloader; the full traceback stays
        # in the log for the rarer genuine load failures.
        logger.warning(
            "Caricamento modello di traduzione fallito (%s)", model_name, exc_info=True
        )
        raise LocalTranslationError(t("local.translation_model_missing")) from exc
    model.eval()

    def translate(text: str) -> str:
        batch = tokenizer([text], return_tensors="pt", truncation=True)
        with torch.no_grad():
            output = model.generate(**batch)
        return tokenizer.batch_decode(output, skip_special_tokens=True)[0]

    return translate
