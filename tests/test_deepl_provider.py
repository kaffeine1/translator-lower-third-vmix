# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""DeepLTranslationProvider tests (v1.2) — httpx.MockTransport, no network.

The live test is active ONLY with DEEPL_API_KEY and RUN_LIVE_TESTS=1.
"""

from __future__ import annotations

import asyncio
import os

import httpx
import pytest

from app.config.secrets import InMemorySecretStore
from app.providers.base import ProviderConfig
from app.providers.deepl import DeepLError, DeepLTranslationProvider


def _store(key="deepl-key-123:fx"):
    store = InMemorySecretStore()
    if key:
        store.set_api_key("deepl", key)
    return store


def _provider(handler, store=None, key="deepl-key-123:fx"):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return DeepLTranslationProvider(store or _store(key), client=client)


# ---------------------------------------------------------------- base url


def test_base_url_selection():
    assert DeepLTranslationProvider.base_url_for_key("abc:fx") == "https://api-free.deepl.com"
    assert DeepLTranslationProvider.base_url_for_key("abc") == "https://api.deepl.com"


# ---------------------------------------------------------------- translate


def test_translate_success_and_request_shape():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, json={"translations": [{"detected_source_language": "ES", "text": "Ciao"}]}
        )

    async def run():
        provider = _provider(handler)
        await provider.connect(ProviderConfig(source_language="es", target_language="it"))
        out = await provider.translate("Hola")
        await provider.close()
        return out

    out = asyncio.run(run())
    assert out == "Ciao"
    request = seen[0]
    assert request.url.path == "/v2/translate"
    assert request.url.host == "api-free.deepl.com"  # key :fx → free endpoint
    assert request.headers["Authorization"].startswith("DeepL-Auth-Key ")
    body = request.content.decode()
    assert "source_lang=ES" in body
    assert "target_lang=IT" in body


def test_translate_empty_text_skips_call():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("non deve chiamare DeepL per testo vuoto")

    async def run():
        provider = _provider(handler)
        await provider.connect(ProviderConfig())
        return await provider.translate("   ")

    assert asyncio.run(run()) == ""


def test_connect_missing_key_raises():
    async def run():
        provider = DeepLTranslationProvider(_store(key=None))
        with pytest.raises(DeepLError):
            await provider.connect(ProviderConfig())

    asyncio.run(run())


def test_auth_error_is_readable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="Forbidden")

    async def run():
        provider = _provider(handler)
        await provider.connect(ProviderConfig())
        with pytest.raises(DeepLError) as excinfo:
            await provider.translate("Hola")
        await provider.close()
        return str(excinfo.value)

    assert "non valida" in asyncio.run(run()).lower()


def test_quota_error_is_readable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(456, text="Quota exceeded")

    async def run():
        provider = _provider(handler)
        await provider.connect(ProviderConfig())
        with pytest.raises(DeepLError) as excinfo:
            await provider.translate("Hola")
        return str(excinfo.value)

    assert "quota" in asyncio.run(run()).lower()


def test_network_error_is_readable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    async def run():
        provider = _provider(handler)
        await provider.connect(ProviderConfig())
        with pytest.raises(DeepLError) as excinfo:
            await provider.translate("Hola")
        return str(excinfo.value)

    assert "Internet" in asyncio.run(run())


# ---------------------------------------------------------------- composed


def test_deepl_inside_composed_provider():
    from app.providers.composed import ComposedRealtimeProvider, FakeSpeechProvider

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"translations": [{"detected_source_language": "ES", "text": "Ciao a tutti"}]}
        )

    async def run():
        speech = FakeSpeechProvider(
            script=[("final", "Hola a todos")], step_delay=0.0, loop=False
        )
        translator = _provider(handler)
        composed = ComposedRealtimeProvider(speech, translator)
        finals: list[str] = []
        composed.on_final_text(finals.append)
        await composed.connect(ProviderConfig())
        for _ in range(20):
            await asyncio.sleep(0)
        await composed.close()
        return finals

    finals = asyncio.run(run())
    assert finals == ["Ciao a tutti"]


# ---------------------------------------------------------------- registry


def test_translation_registry_has_deepl():
    from app.providers.registry import (
        available_translation_providers,
        create_translation_provider,
        get_translation_provider_info,
    )

    ids = [info.id for info in available_translation_providers()]
    assert "deepl" in ids
    assert get_translation_provider_info("deepl").requires_api_key is True
    provider = create_translation_provider("deepl", _store())
    assert isinstance(provider, DeepLTranslationProvider)


def test_deepl_not_in_realtime_selector():
    # DeepL alone must not appear in the GUI selector of realtime providers
    from app.providers.registry import available_providers

    ids = [info.id for info in available_providers()]
    assert "deepl" not in ids


# ---------------------------------------------------------------- live (opt-in)


@pytest.mark.skipif(
    not (os.getenv("DEEPL_API_KEY") and os.getenv("RUN_LIVE_TESTS") == "1"),
    reason="Live test: richiede DEEPL_API_KEY e RUN_LIVE_TESTS=1",
)
def test_live_deepl_translate():
    store = InMemorySecretStore()
    store.set_api_key("deepl", os.environ["DEEPL_API_KEY"])

    async def run():
        provider = DeepLTranslationProvider(store)
        await provider.connect(ProviderConfig(source_language="es", target_language="it"))
        out = await provider.translate("Hola a todos")
        await provider.close()
        return out

    assert asyncio.run(run()).strip() != ""
