# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""OpenAIRealtimeTranslationProvider tests (Realtime Translation protocol).

No real network call: the WebSocket connector is injected with a fake one. The
live test runs ONLY with OPENAI_API_KEY and RUN_LIVE_TESTS=1.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os

import numpy as np
import pytest

from app.config.secrets import InMemorySecretStore
from app.providers.base import ProviderConfig
from app.providers.openai_realtime import (
    OPENAI_INPUT_SAMPLE_RATE,
    OpenAIProviderError,
    OpenAIRealtimeTranslationProvider,
    check_api_key,
)

_RECV_CLOSED = object()


class FakeWebsocket:
    """Fake WebSocket backed by an asyncio.Queue: delivers predefined messages,
    then blocks on recv() until closed. With ``respond_closed`` it answers a
    ``session.close`` request with a ``session.closed`` event (like the server)."""

    def __init__(self, incoming: list[str] | None = None, respond_closed: bool = False) -> None:
        self._queue: asyncio.Queue = asyncio.Queue()
        for message in incoming or []:
            self._queue.put_nowait(message)
        self.sent: list[str] = []
        self.closed = False
        self._respond_closed = respond_closed

    async def send(self, data: str) -> None:
        if self.closed:
            raise ConnectionError("closed")
        self.sent.append(data)
        if self._respond_closed:
            try:
                if json.loads(data).get("type") == "session.close":
                    self._queue.put_nowait(json.dumps({"type": "session.closed"}))
            except (ValueError, TypeError):
                pass

    async def recv(self) -> str:
        item = await self._queue.get()
        if item is _RECV_CLOSED:
            raise ConnectionError("closed")
        return item

    async def close(self) -> None:
        self.closed = True
        self._queue.put_nowait(_RECV_CLOSED)


def _provider(
    incoming=None,
    store=None,
    connector_calls=None,
    respond_closed=False,
    close_timeout_s=0.1,
):
    store = store or InMemorySecretStore()
    store.set_api_key("openai", "sk-test-000000000000")
    ws = FakeWebsocket(incoming, respond_closed=respond_closed)

    async def connector(url, headers):
        if connector_calls is not None:
            connector_calls.append((url, headers))
        return ws

    provider = OpenAIRealtimeTranslationProvider(
        store, connector=connector, close_timeout_s=close_timeout_s
    )
    return provider, ws


def _sink(provider):
    partials, finals, errors = [], [], []
    provider.on_partial_text(partials.append)
    provider.on_final_text(finals.append)
    provider.on_error(errors.append)
    return partials, finals, errors


def _feed(provider, **event):
    """Deliver one JSON event to the provider's message handler."""
    provider._handle_message(json.dumps(event))


# ---------------------------------------------------------------- parsing


def test_output_transcript_deltas_accumulate_as_partials():
    # translated transcript arrives as append-only deltas (no "done" event):
    # they accumulate into a rolling caption emitted as partials.
    provider, _ws = _provider()
    partials, finals, errors = _sink(provider)

    _feed(provider, type="session.output_transcript.delta", delta="Ciao")
    _feed(provider, type="session.output_transcript.delta", delta=" mondo")

    assert partials == ["Ciao", "Ciao mondo"]  # incremental accumulation
    assert finals == []  # continuous translation: no finals
    assert errors == []


def test_output_transcript_resets_after_silence(monkeypatch):
    import app.providers.openai_realtime as mod

    clock = {"t": 1000.0}
    monkeypatch.setattr(mod.time, "monotonic", lambda: clock["t"])
    provider, _ws = _provider()
    partials, _finals, _errors = _sink(provider)

    _feed(provider, type="session.output_transcript.delta", delta="Prima frase")
    clock["t"] += mod.TRANSCRIPT_RESET_S + 1.0  # silence gap -> fresh caption
    _feed(provider, type="session.output_transcript.delta", delta="Seconda")

    assert partials[-1] == "Seconda"  # buffer reset, not "Prima fraseSeconda"


def test_output_transcript_buffer_is_capped():
    import app.providers.openai_realtime as mod

    provider, _ws = _provider()
    partials, _finals, _errors = _sink(provider)
    _feed(provider, type="session.output_transcript.delta", delta="x" * 1000)
    assert len(partials[-1]) == mod.MAX_TRANSCRIPT_CHARS


def test_input_transcript_delta_is_not_forwarded():
    # the source-language transcript is debug/future only: nothing goes to vMix
    provider, _ws = _provider()
    partials, finals, errors = _sink(provider)
    _feed(provider, type="session.input_transcript.delta", delta="hola mundo")
    assert (partials, finals, errors) == ([], [], [])


def test_handle_message_error_maps_invalid_key():
    provider, _ws = _provider()
    _partials, _finals, errors = _sink(provider)
    _feed(provider, type="error", error={"code": "invalid_api_key"})
    assert errors == ["API key non valida"]


def test_handle_message_ignores_non_json():
    provider, _ws = _provider()
    partials, finals, errors = _sink(provider)
    provider._handle_message("non-json")
    assert (partials, finals, errors) == ([], [], [])


# ---------------------------------------------------------------- lifecycle


def test_connect_configures_translation_session_and_never_logs_key():
    async def run():
        calls = []
        provider, ws = _provider(connector_calls=calls)
        await provider.connect(ProviderConfig(source_language="es", target_language="it"))
        # translation endpoint + translate model in the URL
        url, headers = calls[0]
        assert "/v1/realtime/translations" in url
        assert "model=gpt-realtime-translate" in url
        # Bearer header present; no beta header (GA shape); key never leaks
        assert headers["Authorization"].startswith("Bearer ")
        assert "OpenAI-Beta" not in headers
        # first message: session.update with ONLY the OUTPUT language (GA shape;
        # an input.format field would get the session rejected as beta)
        session = json.loads(ws.sent[0])
        assert session["type"] == "session.update"
        assert session["session"]["audio"]["output"]["language"] == "it"
        assert "input" not in session["session"]["audio"]
        await provider.close()
        return provider, ws

    provider, ws = asyncio.run(run())
    assert ws.closed is True
    assert provider._task is None


def test_send_audio_uses_session_append_and_passes_through_at_24k():
    async def run():
        provider, ws = _provider()
        # already at 24 kHz mono → no resampling, bytes unchanged
        await provider.connect(ProviderConfig(sample_rate=OPENAI_INPUT_SAMPLE_RATE))
        await provider.send_audio(b"\x01\x02\x03\x04")
        await provider.close()
        return ws

    ws = asyncio.run(run())
    appends = [
        json.loads(m)
        for m in ws.sent
        if json.loads(m)["type"] == "session.input_audio_buffer.append"
    ]
    assert len(appends) == 1
    assert base64.b64decode(appends[0]["audio"]) == b"\x01\x02\x03\x04"


def test_send_audio_resamples_16k_to_24k():
    async def run():
        provider, ws = _provider()
        await provider.connect(ProviderConfig(sample_rate=16000))
        # 160 mono int16 samples @16k -> expect 240 samples @24k (1.5x)
        samples = np.arange(160, dtype="<i2")
        await provider.send_audio(samples.tobytes())
        await provider.close()
        return ws

    ws = asyncio.run(run())
    appends = [
        base64.b64decode(json.loads(m)["audio"])
        for m in ws.sent
        if json.loads(m)["type"] == "session.input_audio_buffer.append"
    ]
    assert len(appends) == 1
    # 240 int16 samples = 480 bytes
    assert len(appends[0]) == 480


def test_send_audio_downmixes_stereo_to_mono():
    async def run():
        provider, ws = _provider()
        # stereo @ 24 kHz: only down-mix (no rate change)
        await provider.connect(ProviderConfig(sample_rate=OPENAI_INPUT_SAMPLE_RATE, channels=2))
        stereo = np.array([100, 200, 300, 400, 500, 600, 700, 800], dtype="<i2")
        await provider.send_audio(stereo.tobytes())
        await provider.close()
        return ws

    ws = asyncio.run(run())
    appends = [
        base64.b64decode(json.loads(m)["audio"])
        for m in ws.sent
        if json.loads(m)["type"] == "session.input_audio_buffer.append"
    ]
    assert len(appends) == 1
    mono = np.frombuffer(appends[0], dtype="<i2")
    # (L,R) frames averaged: (100,200),(300,400),(500,600),(700,800)
    assert list(mono) == [150, 350, 550, 750]


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
            json.dumps({"type": "session.updated"}),
            json.dumps({"type": "session.output_transcript.delta", "delta": "Ciao"}),
            json.dumps({"type": "session.output_transcript.delta", "delta": " a tutti"}),
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
    assert partials[-1] == "Ciao a tutti"  # deltas accumulated into the caption
    assert finals == []


def test_close_sends_session_close_and_waits_for_closed():
    async def run():
        provider, ws = _provider(respond_closed=True, close_timeout_s=2.0)
        await provider.connect(ProviderConfig())
        await provider.close()
        return provider, ws

    provider, ws = asyncio.run(run())
    sent_types = [json.loads(m)["type"] for m in ws.sent]
    assert "session.close" in sent_types
    assert provider._closed_ack.is_set()  # session.closed was observed
    assert ws.closed is True
    assert provider._task is None


def test_close_without_ack_times_out_without_hanging():
    async def run():
        # server never sends session.closed: close() must still return promptly
        provider, ws = _provider(respond_closed=False, close_timeout_s=0.05)
        await provider.connect(ProviderConfig())
        await provider.close()
        return ws

    ws = asyncio.run(run())
    assert ws.closed is True


def test_intentional_close_after_drop_has_no_connection_lost_error():
    async def run():
        provider, ws = _provider(close_timeout_s=2.0)
        _partials, _finals, errors = _sink(provider)
        await provider.connect(ProviderConfig())
        # stop intent set synchronously, then the socket drops during teardown
        provider.request_close()
        await ws.close()  # recv() raises -> the loop must break, not reconnect
        for _ in range(10):
            await asyncio.sleep(0)
        await provider.close()
        return provider, errors

    provider, errors = asyncio.run(run())
    assert errors == []  # no spurious "connection lost" on an intentional stop
    assert provider._closed_ack.is_set()  # break released the close() waiter
    assert provider._task is None


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
