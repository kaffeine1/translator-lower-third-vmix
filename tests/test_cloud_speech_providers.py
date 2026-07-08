# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""Google/Azure SpeechProvider tests (v1.2) — fake engine, no SDK or network.

The real providers require the optional packages (azure-cognitiveservices-speech,
google-cloud-speech) and are not exercised here.
"""

from __future__ import annotations

import asyncio

import pytest

from app.config.secrets import InMemorySecretStore
from app.providers.azure_speech import AzureSpeechError, AzureSpeechProvider, _lang
from app.providers.base import ProviderConfig
from app.providers.google_speech import GoogleSpeechError, GoogleSpeechProvider


class FakeEngine:
    """Fake engine: records the life cycle and allows simulating events."""

    def __init__(self, **opts) -> None:
        self.opts = opts
        self.started = False
        self.stopped = False
        self.pushed: list[bytes] = []

    def start(self) -> None:
        self.started = True

    def push(self, chunk: bytes) -> None:
        self.pushed.append(chunk)

    def stop(self) -> None:
        self.stopped = True

    # test helper: simulates recognition
    def emit_partial(self, text: str) -> None:
        self.opts["on_partial"](text)

    def emit_final(self, text: str) -> None:
        self.opts["on_final"](text)

    def emit_error(self, text: str) -> None:
        self.opts["on_error"](text)


# ---------------------------------------------------------------- language


def test_language_mapping():
    assert _lang("es") == "es-ES"
    assert _lang("it") == "it-IT"
    assert _lang("en") == "en-US"
    assert _lang("de") == "de-DE"


# ---------------------------------------------------------------- Azure


def _azure_store():
    store = InMemorySecretStore()
    store.set_api_key("azure", "azure-key-123")
    store.set_api_key("azure-region", "westeurope")
    return store


def test_azure_connect_builds_engine_and_emits():
    engines: list[FakeEngine] = []

    def factory(**opts):
        engine = FakeEngine(**opts)
        engines.append(engine)
        return engine

    async def run():
        provider = AzureSpeechProvider(_azure_store(), engine_factory=factory)
        partials, finals, errors = [], [], []
        provider.on_partial_text(partials.append)
        provider.on_final_text(finals.append)
        provider.on_error(errors.append)
        await provider.connect(ProviderConfig(source_language="es"))
        engine = engines[0]
        await provider.send_audio(b"\x01\x02")
        # Azure "recognizing" hypotheses are volatile; the provider stabilizes
        # them append-only, so a single interim commits nothing yet.
        engine.emit_partial("Hola")
        engine.emit_partial("Hola a")
        engine.emit_partial("Hola a todos")
        engine.emit_final("Hola a todos")
        await provider.close()
        return engine, partials, finals

    engine, partials, finals = asyncio.run(run())
    assert engine.started and engine.stopped
    assert engine.opts["language"] == "es-ES"
    assert engine.opts["region"] == "westeurope"
    assert engine.pushed == [b"\x01\x02"]
    # append-only: each partial extends the previous, never rewrites
    assert partials == ["Hola", "Hola a"]
    assert finals == ["Hola a todos"]


def test_azure_missing_key_raises():
    async def run():
        provider = AzureSpeechProvider(InMemorySecretStore(), engine_factory=FakeEngine)
        with pytest.raises(AzureSpeechError):
            await provider.connect(ProviderConfig())

    asyncio.run(run())


def test_azure_missing_region_raises():
    async def run():
        store = InMemorySecretStore()
        store.set_api_key("azure", "k")
        provider = AzureSpeechProvider(store, engine_factory=FakeEngine)
        with pytest.raises(AzureSpeechError) as excinfo:
            await provider.connect(ProviderConfig())
        assert "regione" in str(excinfo.value).lower()

    asyncio.run(run())


def test_azure_real_engine_missing_sdk_is_readable():
    # without the SDK package installed, the real engine gives a readable error
    async def run():
        store = _azure_store()
        provider = AzureSpeechProvider(store)  # real factory
        with pytest.raises(AzureSpeechError) as excinfo:
            await provider.connect(ProviderConfig())
        assert "azure-cognitiveservices-speech" in str(excinfo.value)

    asyncio.run(run())


# ---------------------------------------------------------------- Google


def test_google_connect_builds_engine_and_emits():
    engines: list[FakeEngine] = []

    def factory(**opts):
        engine = FakeEngine(**opts)
        engines.append(engine)
        return engine

    async def run():
        store = InMemorySecretStore()
        store.set_api_key("google", "/percorso/credenziali.json")
        provider = GoogleSpeechProvider(store, engine_factory=factory)
        finals = []
        provider.on_final_text(finals.append)
        await provider.connect(ProviderConfig(source_language="es"))
        engine = engines[0]
        engine.emit_final("Hola a todos")
        await provider.close()
        return engine, finals

    engine, finals = asyncio.run(run())
    assert engine.opts["language"] == "es-ES"
    assert engine.opts["credentials"] == "/percorso/credenziali.json"
    assert engine.stopped
    assert finals == ["Hola a todos"]


def test_google_missing_credentials_raises():
    async def run():
        provider = GoogleSpeechProvider(InMemorySecretStore(), engine_factory=FakeEngine)
        with pytest.raises(GoogleSpeechError):
            await provider.connect(ProviderConfig())

    asyncio.run(run())


def test_google_real_engine_missing_sdk_is_readable():
    async def run():
        store = InMemorySecretStore()
        store.set_api_key("google", "/x.json")
        provider = GoogleSpeechProvider(store)  # real factory
        with pytest.raises(GoogleSpeechError) as excinfo:
            await provider.connect(ProviderConfig())
        assert "google-cloud-speech" in str(excinfo.value)

    asyncio.run(run())


# ------------------------------------------------- interim stabilization (anti-flicker)


def _emitting_google_provider():
    engines: list[FakeEngine] = []

    def factory(**opts):
        engine = FakeEngine(**opts)
        engines.append(engine)
        return engine

    store = InMemorySecretStore()
    store.set_api_key("google", "/creds.json")
    provider = GoogleSpeechProvider(store, engine_factory=factory)
    return provider, engines


def test_google_interim_results_are_stabilized_append_only():
    async def run():
        provider, engines = _emitting_google_provider()
        partials, finals = [], []
        provider.on_partial_text(partials.append)
        provider.on_final_text(finals.append)
        await provider.connect(ProviderConfig(source_language="es"))
        engine = engines[0]
        # Google revises interim transcripts word by word between ticks
        engine.emit_partial("el")
        engine.emit_partial("el sistema")  # commit "el"
        engine.emit_partial("el sistema captura")  # commit "el sistema"
        engine.emit_final("el sistema captura audio")
        await provider.close()
        return partials, finals

    partials, finals = asyncio.run(run())
    assert partials == ["el", "el sistema"]  # append-only prefix, no flicker
    for a, b in zip(partials, partials[1:], strict=False):
        assert b.startswith(a)
    assert finals == ["el sistema captura audio"]


def test_google_revised_interim_word_is_not_rewritten():
    # an already-shown word that Google re-spells must not change on screen
    async def run():
        provider, engines = _emitting_google_provider()
        partials = []
        provider.on_partial_text(partials.append)
        await provider.connect(ProviderConfig(source_language="es"))
        engine = engines[0]
        engine.emit_partial("buenos dias")
        engine.emit_partial("buenos dias a")  # commit "buenos dias"
        engine.emit_partial("buenas dias a todos")  # "buenos" -> "buenas"
        await provider.close()
        return partials

    partials = asyncio.run(run())
    assert all("buenas" not in p for p in partials)
    assert partials == ["buenos dias"]


def test_final_resets_interim_stabilization():
    # after a final the next caption's interim stream starts fresh
    async def run():
        provider, engines = _emitting_google_provider()
        partials, finals = [], []
        provider.on_partial_text(partials.append)
        provider.on_final_text(finals.append)
        await provider.connect(ProviderConfig(source_language="es"))
        engine = engines[0]
        engine.emit_partial("uno")
        engine.emit_partial("uno dos")  # commit "uno"
        engine.emit_final("uno dos tres")
        engine.emit_partial("cuatro")  # fresh caption: nothing committed yet
        engine.emit_partial("cuatro cinco")  # commit "cuatro"
        await provider.close()
        return partials, finals

    partials, finals = asyncio.run(run())
    assert partials == ["uno", "cuatro"]
    assert finals == ["uno dos tres"]


# ---------------------------------------------------------------- composed cloud


def test_cloud_speech_composed_with_deepl():
    # Azure Speech (fake) → DeepL (mock httpx): full cloud pipeline
    import httpx

    from app.providers.composed import ComposedRealtimeProvider
    from app.providers.deepl import DeepLTranslationProvider

    engines: list[FakeEngine] = []

    def factory(**opts):
        engine = FakeEngine(**opts)
        engines.append(engine)
        return engine

    def deepl_handler(request):
        return httpx.Response(
            200, json={"translations": [{"detected_source_language": "ES", "text": "Ciao a tutti"}]}
        )

    async def run():
        speech = AzureSpeechProvider(_azure_store(), engine_factory=factory)
        deepl_store = InMemorySecretStore()
        deepl_store.set_api_key("deepl", "k:fx")
        translator = DeepLTranslationProvider(
            deepl_store, client=httpx.AsyncClient(transport=httpx.MockTransport(deepl_handler))
        )
        composed = ComposedRealtimeProvider(speech, translator)
        finals = []
        composed.on_final_text(finals.append)
        await composed.connect(ProviderConfig(source_language="es", target_language="it"))
        engines[0].emit_final("Hola a todos")
        for _ in range(20):
            await asyncio.sleep(0)
        await composed.close()
        return finals

    finals = asyncio.run(run())
    assert finals == ["Ciao a tutti"]


# ---------------------------------------------------------------- registry


def test_speech_registry():
    from app.providers.registry import (
        available_speech_providers,
        create_speech_provider,
        get_speech_provider_info,
    )

    ids = [info.id for info in available_speech_providers()]
    assert {"google", "azure", "fake-speech"} <= set(ids)
    assert get_speech_provider_info("google").required_key_names == ("google",)
    assert isinstance(
        create_speech_provider("azure", _azure_store()), AzureSpeechProvider
    )


def test_create_composed_provider_via_registry():
    from app.providers.composed import ComposedRealtimeProvider
    from app.providers.registry import create_composed_provider

    store = _azure_store()
    store.set_api_key("deepl", "k:fx")
    provider = create_composed_provider("azure", "deepl", store)
    assert isinstance(provider, ComposedRealtimeProvider)


def test_cloud_speech_not_in_realtime_selector():
    from app.providers.registry import available_providers

    ids = [info.id for info in available_providers()]
    assert "google" not in ids
    assert "azure" not in ids
