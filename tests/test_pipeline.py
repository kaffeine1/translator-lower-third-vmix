# Translator Lower Third for vMix
# Autore: Michele Dipace <michele.dipace@kaffeine.net>
"""TranslationPipeline integration tests (Milestone 6).

Provider finto → formatter → uscita finta. Verificano il flusso end-to-end e
soprattutto che STOP non lasci thread appesi.
"""

from __future__ import annotations

import threading
import time

from app.config.models import AppConfig
from app.pipeline import TranslationPipeline
from app.providers.fake import FakeTranslationProvider


class _Collector:
    """Raccoglie in modo thread-safe i sottotitoli/uscite dai vari thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.items: list[str] = []

    def __call__(self, text: str) -> None:
        with self._lock:
            self.items.append(text)

    def snapshot(self) -> list[str]:
        with self._lock:
            return list(self.items)


def _wait_until(predicate, timeout=5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def _fast_config() -> AppConfig:
    config = AppConfig()
    # intervallo breve così i parziali/finali passano in fretta nei test
    config.subtitles.min_update_interval_ms = 100
    return config


def test_pipeline_end_to_end_produces_subtitles():
    preview = _Collector()
    output = _Collector()
    provider = FakeTranslationProvider(
        script=[("partial", "Ciao"), ("final", "Ciao a tutti")],
        step_delay=0.02,
        loop=False,
    )
    pipeline = TranslationPipeline(
        provider,
        _fast_config(),
        on_subtitle=preview,
        output_publish=output,
    )
    pipeline.start()
    try:
        assert _wait_until(lambda: "Ciao a tutti" in output.snapshot())
        # il testo raggiunge sia l'anteprima GUI sia l'uscita (vMix)
        assert "Ciao a tutti" in preview.snapshot()
    finally:
        pipeline.stop()


def test_pipeline_stop_leaves_no_hanging_threads():
    provider = FakeTranslationProvider(step_delay=0.05)  # loop infinito
    pipeline = TranslationPipeline(
        provider, _fast_config(), on_subtitle=_Collector(), output_publish=_Collector()
    )
    before = set(threading.enumerate())
    pipeline.start()
    assert _wait_until(lambda: len(threading.enumerate()) > len(before))
    pipeline.stop()
    # i thread della pipeline devono essere tutti terminati
    assert _wait_until(
        lambda: not any(
            t.name.startswith("pipeline-") for t in threading.enumerate()
        ),
        timeout=8,
    )


def test_pipeline_forwards_provider_error():
    errors = _Collector()
    provider = FakeTranslationProvider(
        script=[("partial", "a"), ("final", "b")],
        step_delay=0.02,
        fail_at_index=0,
        loop=False,
    )
    pipeline = TranslationPipeline(
        provider,
        _fast_config(),
        on_subtitle=_Collector(),
        output_publish=_Collector(),
        on_error=errors,
    )
    pipeline.start()
    try:
        assert _wait_until(lambda: len(errors.snapshot()) > 0)
        assert "Connessione persa" in errors.snapshot()[0]
    finally:
        pipeline.stop()


def test_pipeline_survives_output_that_raises():
    # se l'uscita (vMix) solleva, la pipeline non deve cadere né bloccarsi
    preview = _Collector()

    def broken_output(text: str) -> None:
        raise RuntimeError("vMix giù")

    provider = FakeTranslationProvider(
        script=[("final", "Prima"), ("final", "Seconda")],
        step_delay=0.02,
        loop=False,
    )
    pipeline = TranslationPipeline(
        provider, _fast_config(), on_subtitle=preview, output_publish=broken_output
    )
    pipeline.start()
    try:
        # l'anteprima continua a ricevere nonostante l'uscita rotta
        assert _wait_until(lambda: "Seconda" in preview.snapshot())
    finally:
        pipeline.stop()


def test_pipeline_double_start_is_safe():
    provider = FakeTranslationProvider(step_delay=0.05)
    pipeline = TranslationPipeline(
        provider, _fast_config(), on_subtitle=_Collector(), output_publish=_Collector()
    )
    pipeline.start()
    try:
        pipeline.start()  # secondo start ignorato, nessuna eccezione
    finally:
        pipeline.stop()
    pipeline.stop()  # secondo stop ignorato
