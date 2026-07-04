# Translator Lower Third for vMix
# Autore: Michele Dipace <michele.dipace@kaffeine.net>
"""SpeechProvider / TranslationProvider split + ComposedRealtimeProvider (v1.1).

Nessuna rete: tutto con implementazioni finte e asyncio.
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
    assert finals == ["Hola a todos"]  # testo SORGENTE, non tradotto


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
    assert passthrough == "desconocido"  # fuori mappa: identità


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
        # lascia scorrere lo script e le traduzioni
        for _ in range(20):
            await asyncio.sleep(0)
        await composed.close()
        return partials, finals, errors

    partials, finals, errors = asyncio.run(run())
    assert finals == ["Ciao a tutti"]  # tradotto
    assert "Ciao" in partials
    assert errors == []


def test_composed_is_a_realtime_provider():
    composed = make_demo_composed_provider()
    assert isinstance(composed, RealtimeTranslationProvider)


def test_composed_final_supersedes_stale_partial():
    async def run():
        # traduttore lento sui parziali: il finale deve prevalere e i parziali
        # in ritardo non devono riemergere dopo il finale
        script = [("partial", "uno"), ("final", "uno due tre")]
        speech = FakeSpeechProvider(script=script, step_delay=0.0, loop=False)

        class SlowPartialTranslator(FakeTranslationTextProvider):
            async def translate(self, text: str) -> str:
                if text == "uno":
                    await asyncio.sleep(0.05)  # parziale lento
                return {"uno": "1", "uno due tre": "1 2 3"}.get(text, text)

        composed = ComposedRealtimeProvider(speech, SlowPartialTranslator())
        partials, finals, _errors = _sink(composed)
        await composed.connect(ProviderConfig())
        await asyncio.sleep(0.2)
        await composed.close()
        return partials, finals

    partials, finals = asyncio.run(run())
    assert finals == ["1 2 3"]
    # il parziale lento "1" è stato scartato perché superato dal finale
    assert partials == []


def test_composed_drops_translation_completed_after_close():
    # regressione: se la traduzione finisce DOPO lo STOP, non deve emettere un
    # sottotitolo stantìo (che finirebbe in onda a evento concluso)
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
        for _ in range(10):  # avvia la traduzione (resta in attesa sul gate)
            await asyncio.sleep(0)
        await composed.close()  # STOP prima che la traduzione finisca
        gate.set()  # ora la traduzione completa
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
    # end-to-end: il provider composto funziona nella TranslationPipeline reale
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
