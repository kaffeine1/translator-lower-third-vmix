# Translator Lower Third for vMix
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""SpeechProvider / TranslationProvider split + ComposedRealtimeProvider (v1.1).

No network: everything with fake implementations and asyncio.
"""

from __future__ import annotations

import asyncio

from app.providers.base import (
    ProviderConfig,
    RealtimeTranslationProvider,
)
from app.providers.composed import (
    ComposedRealtimeProvider,
    FakeSpeechProvider,
    FakeTranslationTextProvider,
    make_demo_composed_provider,
)


def _sink(provider):
    partials, finals, errors = [], [], []
    provider.on_partial_text(partials.append)
    provider.on_final_text(finals.append)
    provider.on_error(errors.append)
    return partials, finals, errors


# ---------------------------------------------------------------- fake speech


def test_fake_speech_emits_source_text():
    async def run():
        script = [("partial", "Hola"), ("final", "Hola a todos")]
        speech = FakeSpeechProvider(script=script, step_delay=0.0, loop=False)
        partials, finals, _errors = _sink(speech)
        await speech.connect(ProviderConfig())
        await asyncio.wait_for(speech._task, timeout=2)
        return partials, finals

    partials, finals = asyncio.run(run())
    assert partials == ["Hola"]
    assert finals == ["Hola a todos"]  # SOURCE text, not translated


def test_fake_speech_clean_shutdown():
    async def run():
        speech = FakeSpeechProvider(step_delay=10.0)
        await speech.connect(ProviderConfig())
        task = speech._task
        await speech.close()
        return task

    task = asyncio.run(run())
    assert task.done()


# ---------------------------------------------------------------- fake translator


def test_fake_translator_maps_and_falls_back():
    async def run():
        translator = FakeTranslationTextProvider(mapping={"Hola": "Ciao"})
        mapped = await translator.translate("Hola")
        passthrough = await translator.translate("desconocido")
        return mapped, passthrough

    mapped, passthrough = asyncio.run(run())
    assert mapped == "Ciao"
    assert passthrough == "desconocido"  # off the map: identity


# ---------------------------------------------------------------- composed


def test_composed_translates_source_to_target():
    async def run():
        script = [("partial", "Hola"), ("final", "Hola a todos")]
        speech = FakeSpeechProvider(script=script, step_delay=0.0, loop=False)
        translator = FakeTranslationTextProvider(
            mapping={"Hola": "Ciao", "Hola a todos": "Ciao a tutti"}
        )
        composed = ComposedRealtimeProvider(speech, translator)
        partials, finals, errors = _sink(composed)
        await composed.connect(ProviderConfig())
        # let the script and translations flow
        for _ in range(20):
            await asyncio.sleep(0)
        await composed.close()
        return partials, finals, errors

    partials, finals, errors = asyncio.run(run())
    assert finals == ["Ciao a tutti"]  # translated
    assert "Ciao" in partials
    assert errors == []


def test_composed_is_a_realtime_provider():
    composed = make_demo_composed_provider()
    assert isinstance(composed, RealtimeTranslationProvider)


def test_composed_final_supersedes_stale_partial():
    async def run():
        # translator slow on partials: the final must win and the late
        # partials must not re-emerge after the final
        script = [("partial", "uno"), ("final", "uno due tre")]
        speech = FakeSpeechProvider(script=script, step_delay=0.0, loop=False)

        class SlowPartialTranslator(FakeTranslationTextProvider):
            async def translate(self, text: str) -> str:
                if text == "uno":
                    await asyncio.sleep(0.05)  # slow partial
                return {"uno": "1", "uno due tre": "1 2 3"}.get(text, text)

        composed = ComposedRealtimeProvider(speech, SlowPartialTranslator())
        partials, finals, _errors = _sink(composed)
        await composed.connect(ProviderConfig())
        await asyncio.sleep(0.2)
        await composed.close()
        return partials, finals

    partials, finals = asyncio.run(run())
    assert finals == ["1 2 3"]
    # the slow partial "1" was discarded because superseded by the final
    assert partials == []


def test_composed_drops_translation_completed_after_close():
    # regression: if the translation finishes AFTER the STOP, it must not emit a
    # stale subtitle (which would go on air after the event has ended)
    from app.providers.base import TranslationProvider

    async def run():
        gate = asyncio.Event()

        class GatedTranslator(TranslationProvider):
            async def translate(self, text: str) -> str:
                await gate.wait()
                return "TRADOTTO"

        speech = FakeSpeechProvider(
            script=[("final", "hola")], step_delay=0.0, loop=False
        )
        composed = ComposedRealtimeProvider(speech, GatedTranslator())
        finals: list[str] = []
        composed.on_final_text(finals.append)
        await composed.connect(ProviderConfig())
        for _ in range(10):  # start the translation (stays waiting on the gate)
            await asyncio.sleep(0)
        await composed.close()  # STOP before the translation finishes
        gate.set()  # now the translation completes
        for _ in range(10):
            await asyncio.sleep(0)
        return finals

    assert asyncio.run(run()) == []


def test_composed_provider_via_registry():
    from app.providers.registry import create_provider, get_provider_info

    info = get_provider_info("demo-composed")
    assert info is not None and info.requires_api_key is False
    provider = create_provider("demo-composed", None)
    assert isinstance(provider, ComposedRealtimeProvider)


def test_composed_runs_through_pipeline():
    # end-to-end: the composed provider works in the real TranslationPipeline
    import threading
    import time

    from app.config.models import AppConfig
    from app.pipeline import TranslationPipeline

    lock = threading.Lock()
    outputs: list[str] = []

    def collect(text):
        with lock:
            outputs.append(text)

    script = [("final", "Hola a todos")]
    speech = FakeSpeechProvider(script=script, step_delay=0.02, loop=False)
    translator = FakeTranslationTextProvider(mapping={"Hola a todos": "Ciao a tutti"})
    composed = ComposedRealtimeProvider(speech, translator)

    config = AppConfig()
    config.subtitles.min_update_interval_ms = 100
    pipeline = TranslationPipeline(
        composed, config, on_subtitle=collect, output_publish=lambda t: None
    )
    pipeline.start()
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with lock:
                if "Ciao a tutti" in outputs:
                    break
            time.sleep(0.02)
        with lock:
            assert "Ciao a tutti" in outputs
    finally:
        pipeline.stop()
