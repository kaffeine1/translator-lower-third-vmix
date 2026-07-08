# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""GoogleTranslateProvider tests — httpx.MockTransport, no network.

The live test is active ONLY with GOOGLE_TRANSLATE_API_KEY and RUN_LIVE_TESTS=1.
"""

from __future__ import annotations

import asyncio
import os

import httpx
import pytest

from app.config.secrets import InMemorySecretStore
from app.providers.base import ProviderConfig
from app.providers.google_translate import GoogleTranslateError, GoogleTranslateProvider


def _store(key="gt-key-123"):
    store = InMemorySecretStore()
    if key:
        store.set_api_key("google-translate", key)
    return store


def _provider(handler, store=None, key="gt-key-123"):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return GoogleTranslateProvider(store or _store(key), client=client)


def _ok(text):
    return httpx.Response(200, json={"data": {"translations": [{"translatedText": text}]}})


def test_translate_success_and_request_shape():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _ok("Ciao")

    async def run():
        provider = _provider(handler)
        await provider.connect(ProviderConfig(source_language="es", target_language="it"))
        out = await provider.translate("Hola")
        await provider.close()
        return out

    out = asyncio.run(run())
    assert out == "Ciao"
    request = seen[0]
    assert request.url.path == "/language/translate/v2"
    assert request.url.host == "translation.googleapis.com"
    assert request.url.params["key"] == "gt-key-123"
    body = request.content.decode()
    assert '"source": "es"' in body or '"source":"es"' in body
    assert '"target": "it"' in body or '"target":"it"' in body
    assert '"text"' in body  # format=text requested


def test_html_entities_are_unescaped():
    def handler(request: httpx.Request) -> httpx.Response:
        # even asking format=text, be defensive against stray entities
        return _ok("L&#39;acqua &amp; il fuoco")

    async def run():
        provider = _provider(handler)
        await provider.connect(ProviderConfig(source_language="es", target_language="it"))
        out = await provider.translate("El agua y el fuego")
        await provider.close()
        return out

    assert asyncio.run(run()) == "L'acqua & il fuoco"


def test_translate_empty_text_skips_call():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("non deve chiamare Google per testo vuoto")

    async def run():
        provider = _provider(handler)
        await provider.connect(ProviderConfig())
        return await provider.translate("   ")

    assert asyncio.run(run()) == ""


def test_connect_missing_key_raises():
    async def run():
        provider = GoogleTranslateProvider(_store(key=None))
        with pytest.raises(GoogleTranslateError):
            await provider.connect(ProviderConfig())

    asyncio.run(run())


def test_forbidden_error_is_readable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="PERMISSION_DENIED")

    async def run():
        provider = _provider(handler)
        await provider.connect(ProviderConfig())
        with pytest.raises(GoogleTranslateError) as excinfo:
            await provider.translate("Hola")
        await provider.close()
        return str(excinfo.value)

    assert "chiave" in asyncio.run(run()).lower()


def test_network_error_is_readable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    async def run():
        provider = _provider(handler)
        await provider.connect(ProviderConfig())
        with pytest.raises(GoogleTranslateError) as excinfo:
            await provider.translate("Hola")
        return str(excinfo.value)

    assert "Internet" in asyncio.run(run())


def test_registry_and_composed_pipeline():
    from app.providers.composed import ComposedRealtimeProvider, FakeSpeechProvider
    from app.providers.registry import (
        available_providers,
        available_translation_providers,
        create_translation_provider,
    )

    ids = [i.id for i in available_translation_providers()]
    assert "google-translate" in ids
    assert isinstance(
        create_translation_provider("google-translate", _store()), GoogleTranslateProvider
    )
    # the full same-vendor pipeline appears in the realtime selector
    realtime = [i.id for i in available_providers()]
    assert "google-google" in realtime

    def handler(request: httpx.Request) -> httpx.Response:
        return _ok("Ciao a tutti")

    async def run():
        speech = FakeSpeechProvider(script=[("final", "Hola a todos")], step_delay=0.0, loop=False)
        composed = ComposedRealtimeProvider(speech, _provider(handler))
        finals: list[str] = []
        composed.on_final_text(finals.append)
        await composed.connect(ProviderConfig())
        for _ in range(20):
            await asyncio.sleep(0)
        await composed.close()
        return finals

    assert asyncio.run(run()) == ["Ciao a tutti"]


@pytest.mark.skipif(
    not (os.getenv("GOOGLE_TRANSLATE_API_KEY") and os.getenv("RUN_LIVE_TESTS") == "1"),
    reason="Live test: richiede GOOGLE_TRANSLATE_API_KEY e RUN_LIVE_TESTS=1",
)
def test_live_google_translate():
    store = InMemorySecretStore()
    store.set_api_key("google-translate", os.environ["GOOGLE_TRANSLATE_API_KEY"])

    async def run():
        provider = GoogleTranslateProvider(store)
        await provider.connect(ProviderConfig(source_language="es", target_language="it"))
        out = await provider.translate("Hola a todos")
        await provider.close()
        return out

    assert asyncio.run(run()).strip() != ""
