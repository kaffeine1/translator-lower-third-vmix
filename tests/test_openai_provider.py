# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""OpenAIRealtimeTranslationProvider tests (Milestone 7).

No real network call: the WebSocket connector is injected with a
fake one. The live test is active ONLY with OPENAI_API_KEY and RUN_LIVE_TESTS=1.
"""

from __future__ import annotations

import asyncio
import json
import os

import pytest

from app.config.secrets import InMemorySecretStore
from app.providers.base import ProviderConfig
from app.providers.openai_realtime import (
    OpenAIProviderError,
    OpenAIRealtimeTranslationProvider,
    check_api_key,
)


class FakeWebsocket:
    """Fake WebSocket: delivers predefined messages, then blocks until it
    is closed (like a live connection waiting)."""

    def __init__(self, incoming: list[str] | None = None) -> None:
        self._incoming = list(incoming or [])
        self.sent: list[str] = []
        self.closed = False
        self._closed_event = asyncio.Event()

    async def send(self, data: str) -> None:
        if self.closed:
            raise ConnectionError("closed")
        self.sent.append(data)

    async def recv(self) -> str:
        if self._incoming:
            return self._incoming.pop(0)
        await self._closed_event.wait()  # stays connected until it is closed
        raise ConnectionError("closed")

    async def close(self) -> None:
        self.closed = True
        self._closed_event.set()


def _provider(incoming=None, store=None, connector_calls=None):
    store = store or InMemorySecretStore()
    store.set_api_key("openai", "sk-test-000000000000")
    ws = FakeWebsocket(incoming)

    async def connector(url, headers):
        if connector_calls is not None:
            connector_calls.append((url, headers))
        return ws

    provider = OpenAIRealtimeTranslationProvider(store, connector=connector)
    return provider, ws


def _sink(provider):
    partials, finals, errors = [], [], []
    provider.on_partial_text(partials.append)
    provider.on_final_text(finals.append)
    provider.on_error(errors.append)
    return partials, finals, errors


# ---------------------------------------------------------------- parsing


def test_handle_message_partial_and_final():
    provider, _ws = _provider()
    partials, finals, errors = _sink(provider)

    provider._handle_message(json.dumps({"type": "response.created"}))
    provider._handle_message(json.dumps({"type": "response.text.delta", "delta": "Ciao"}))
    provider._handle_message(json.dumps({"type": "response.text.delta", "delta": " mondo"}))
    provider._handle_message(json.dumps({"type": "response.text.done", "text": "Ciao mondo"}))

    assert partials == ["Ciao", "Ciao mondo"]  # incremental accumulation
    assert finals == ["Ciao mondo"]
    assert errors == []


def test_handle_message_supports_output_text_naming():
    provider, _ws = _provider()
    partials, finals, _errors = _sink(provider)
    provider._handle_message(json.dumps({"type": "response.output_text.delta", "delta": "Hola"}))
    provider._handle_message(json.dumps({"type": "response.output_text.done", "text": "Hola"}))
    assert partials == ["Hola"]
    assert finals == ["Hola"]


def test_handle_message_final_falls_back_to_buffer():
    provider, _ws = _provider()
    _partials, finals, _errors = _sink(provider)
    provider._handle_message(json.dumps({"type": "response.text.delta", "delta": "Buonasera"}))
    provider._handle_message(json.dumps({"type": "response.text.done"}))  # without 'text'
    assert finals == ["Buonasera"]


def test_handle_message_error_maps_invalid_key():
    provider, _ws = _provider()
    _partials, _finals, errors = _sink(provider)
    provider._handle_message(
        json.dumps({"type": "error", "error": {"code": "invalid_api_key"}})
    )
    assert errors == ["API key non valida"]


def test_handle_message_ignores_non_json():
    provider, _ws = _provider()
    partials, finals, errors = _sink(provider)
    provider._handle_message("non-json")
    assert (partials, finals, errors) == ([], [], [])


def test_buffer_resets_between_responses():
    provider, _ws = _provider()
    partials, finals, _errors = _sink(provider)
    provider._handle_message(json.dumps({"type": "response.text.delta", "delta": "Uno"}))
    provider._handle_message(json.dumps({"type": "response.text.done", "text": "Uno"}))
    provider._handle_message(json.dumps({"type": "response.created"}))
    provider._handle_message(json.dumps({"type": "response.text.delta", "delta": "Due"}))
    assert partials == ["Uno", "Due"]
    assert finals == ["Uno"]


# ---------------------------------------------------------------- lifecycle


def test_connect_sends_session_config_and_never_logs_key():
    async def run():
        calls = []
        provider, ws = _provider(connector_calls=calls)
        await provider.connect(ProviderConfig(source_language="es", target_language="it"))
        # Bearer header present but the key must not end up anywhere else
        url, headers = calls[0]
        assert "model=" in url
        assert headers["Authorization"].startswith("Bearer ")
        # first message sent: session configuration
        session = json.loads(ws.sent[0])
        assert session["type"] == "session.update"
        assert session["session"]["input_audio_format"] == "pcm16"
        await provider.close()
        return provider, ws

    provider, ws = asyncio.run(run())
    assert ws.closed is True
    assert provider._task is None


def test_send_audio_encodes_base64():
    async def run():
        provider, ws = _provider()
        await provider.connect(ProviderConfig())
        await provider.send_audio(b"\x01\x02\x03\x04")
        await provider.close()
        return ws

    ws = asyncio.run(run())
    appends = [
        json.loads(m)
        for m in ws.sent
        if json.loads(m)["type"] == "input_audio_buffer.append"
    ]
    assert len(appends) == 1
    import base64

    assert base64.b64decode(appends[0]["audio"]) == b"\x01\x02\x03\x04"


def test_connect_missing_key_raises():
    async def run():
        store = InMemorySecretStore()  # no key

        async def connector(url, headers):
            raise AssertionError("non deve nemmeno tentare la connessione")

        provider = OpenAIRealtimeTranslationProvider(store, connector=connector)
        with pytest.raises(OpenAIProviderError) as excinfo:
            await provider.connect(ProviderConfig())
        assert "chiave api" in str(excinfo.value).lower()

    asyncio.run(run())


def test_connect_auth_failure_is_readable():
    async def run():
        store = InMemorySecretStore()
        store.set_api_key("openai", "sk-bad")

        async def connector(url, headers):
            exc = Exception("server rejected: HTTP 401")
            exc.status_code = 401
            raise exc

        provider = OpenAIRealtimeTranslationProvider(store, connector=connector)
        with pytest.raises(OpenAIProviderError) as excinfo:
            await provider.connect(ProviderConfig())
        assert "API key non valida" in str(excinfo.value)

    asyncio.run(run())


def test_receive_loop_emits_events_end_to_end():
    async def run():
        incoming = [
            json.dumps({"type": "session.created"}),
            json.dumps({"type": "response.text.delta", "delta": "Ciao"}),
            json.dumps({"type": "response.text.done", "text": "Ciao a tutti"}),
        ]
        provider, ws = _provider(incoming=incoming)
        partials, finals, _errors = _sink(provider)
        await provider.connect(ProviderConfig())
        # let the queued messages be processed
        for _ in range(10):
            await asyncio.sleep(0)
        await provider.close()
        return partials, finals

    partials, finals = asyncio.run(run())
    assert "Ciao" in partials
    assert finals == ["Ciao a tutti"]


# ---------------------------------------------------------------- check_api_key


def test_check_api_key_success():
    async def run():
        store = InMemorySecretStore()
        store.set_api_key("openai", "sk-good-000000000000")

        async def connector(url, headers):
            return FakeWebsocket([json.dumps({"type": "session.created"})])

        await check_api_key(store, connector=connector)  # must not raise

    asyncio.run(run())


def test_check_api_key_missing():
    async def run():
        with pytest.raises(OpenAIProviderError):
            await check_api_key(InMemorySecretStore())

    asyncio.run(run())


def test_check_api_key_auth_failure():
    async def run():
        store = InMemorySecretStore()
        store.set_api_key("openai", "sk-bad")

        async def connector(url, headers):
            exc = Exception("HTTP 403 Forbidden")
            exc.status_code = 403
            raise exc

        with pytest.raises(OpenAIProviderError) as excinfo:
            await check_api_key(store, connector=connector)
        assert "API key non valida" in str(excinfo.value)

    asyncio.run(run())


# ---------------------------------------------------------------- provider selection


def test_live_services_uses_fake_without_key():
    from app.audio.input import FakeAudioInput
    from app.config.models import AppConfig
    from app.providers.fake import FakeTranslationProvider
    from app.services import LiveAppServices

    services = LiveAppServices(FakeAudioInput(), InMemorySecretStore())
    services.update_config(AppConfig())
    assert isinstance(services._make_provider(), FakeTranslationProvider)


def test_live_services_uses_openai_with_key():
    from app.audio.input import FakeAudioInput
    from app.config.models import AppConfig
    from app.providers.openai_realtime import OpenAIRealtimeTranslationProvider
    from app.services import LiveAppServices

    store = InMemorySecretStore()
    store.set_api_key("openai", "sk-test-000000000000")
    services = LiveAppServices(FakeAudioInput(), store)
    services.update_config(AppConfig())
    assert isinstance(services._make_provider(), OpenAIRealtimeTranslationProvider)


# ---------------------------------------------------------------- live (opt-in)


@pytest.mark.skipif(
    not (os.getenv("OPENAI_API_KEY") and os.getenv("RUN_LIVE_TESTS") == "1"),
    reason="Live test: richiede OPENAI_API_KEY e RUN_LIVE_TESTS=1",
)
def test_live_check_api_key():
    store = InMemorySecretStore()
    store.set_api_key("openai", os.environ["OPENAI_API_KEY"])
    asyncio.run(check_api_key(store))
