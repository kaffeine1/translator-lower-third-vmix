# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""TranslationPipeline integration tests (Milestone 6).

Fake provider → formatter → fake output. They verify the end-to-end flow and
above all that STOP does not leave hanging threads.
"""

from __future__ import annotations

import threading
import time

from app.config.models import AppConfig
from app.pipeline import TranslationPipeline
from app.providers.fake import FakeTranslationProvider


class _Collector:
    """Collects subtitles/outputs from the various threads in a thread-safe way."""

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
    # short interval so partials/finals pass through quickly in the tests
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
        # the text reaches both the GUI preview and the output (vMix)
        assert "Ciao a tutti" in preview.snapshot()
    finally:
        pipeline.stop()


def test_pipeline_stop_leaves_no_hanging_threads():
    provider = FakeTranslationProvider(step_delay=0.05)  # infinite loop
    pipeline = TranslationPipeline(
        provider, _fast_config(), on_subtitle=_Collector(), output_publish=_Collector()
    )
    before = set(threading.enumerate())
    pipeline.start()
    assert _wait_until(lambda: len(threading.enumerate()) > len(before))
    pipeline.stop()
    # the pipeline threads must all be terminated
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
    # if the output (vMix) raises, the pipeline must not crash nor block
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
        # the preview keeps receiving despite the broken output
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
        pipeline.start()  # second start ignored, no exception
    finally:
        pipeline.stop()
    pipeline.stop()  # second stop ignored
