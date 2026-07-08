# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""AzureTranslatorProvider tests — httpx.MockTransport, no network.

The live test is active ONLY with AZURE_TRANSLATOR_KEY, AZURE_TRANSLATOR_REGION
and RUN_LIVE_TESTS=1.
"""

from __future__ import annotations

import asyncio
import os

import httpx
import pytest

from app.config.secrets import InMemorySecretStore
from app.providers.azure_translate import AzureTranslatorError, AzureTranslatorProvider
from app.providers.base import ProviderConfig


def _store(key="az-key-123", region="westeurope"):
    store = InMemorySecretStore()
    if key:
        store.set_api_key("azure", key)
    if region:
        store.set_api_key("azure-region", region)
    return store


def _provider(handler, store=None):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return AzureTranslatorProvider(store or _store(), client=client)


def _ok(text):
    return httpx.Response(200, json=[{"translations": [{"text": text, "to": "it"}]}])


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
    assert request.url.host == "api.cognitive.microsofttranslator.com"
    assert request.url.path == "/translate"
    assert request.url.params["api-version"] == "3.0"
    assert request.url.params["from"] == "es"
    assert request.url.params["to"] == "it"
    assert request.headers["Ocp-Apim-Subscription-Key"] == "az-key-123"
    assert request.headers["Ocp-Apim-Subscription-Region"] == "westeurope"
    assert '"Text"' in request.content.decode()


def test_translate_empty_text_skips_call():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("non deve chiamare Azure per testo vuoto")

    async def run():
        provider = _provider(handler)
        await provider.connect(ProviderConfig())
        return await provider.translate("   ")

    assert asyncio.run(run()) == ""


def test_connect_missing_key_raises():
    async def run():
        provider = AzureTranslatorProvider(_store(key=None))
        with pytest.raises(AzureTranslatorError):
            await provider.connect(ProviderConfig())

    asyncio.run(run())


def test_connect_missing_region_raises():
    async def run():
        provider = AzureTranslatorProvider(_store(region=None))
        with pytest.raises(AzureTranslatorError) as excinfo:
            await provider.connect(ProviderConfig())
        assert "regione" in str(excinfo.value).lower()

    asyncio.run(run())


def test_auth_error_is_readable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Unauthorized")

    async def run():
        provider = _provider(handler)
        await provider.connect(ProviderConfig())
        with pytest.raises(AzureTranslatorError) as excinfo:
            await provider.translate("Hola")
        await provider.close()
        return str(excinfo.value)

    assert "non valida" in asyncio.run(run()).lower()


def test_network_error_is_readable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    async def run():
        provider = _provider(handler)
        await provider.connect(ProviderConfig())
        with pytest.raises(AzureTranslatorError) as excinfo:
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
    assert "azure-translator" in ids
    assert isinstance(
        create_translation_provider("azure-translator", _store()), AzureTranslatorProvider
    )
    realtime = [i.id for i in available_providers()]
    assert "azure-azure" in realtime

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
    not (
        os.getenv("AZURE_TRANSLATOR_KEY")
        and os.getenv("AZURE_TRANSLATOR_REGION")
        and os.getenv("RUN_LIVE_TESTS") == "1"
    ),
    reason="Live test: richiede AZURE_TRANSLATOR_KEY, AZURE_TRANSLATOR_REGION e RUN_LIVE_TESTS=1",
)
def test_live_azure_translate():
    store = InMemorySecretStore()
    store.set_api_key("azure", os.environ["AZURE_TRANSLATOR_KEY"])
    store.set_api_key("azure-region", os.environ["AZURE_TRANSLATOR_REGION"])

    async def run():
        provider = AzureTranslatorProvider(store)
        await provider.connect(ProviderConfig(source_language="es", target_language="it"))
        out = await provider.translate("Hola a todos")
        await provider.close()
        return out

    assert asyncio.run(run()).strip() != ""
