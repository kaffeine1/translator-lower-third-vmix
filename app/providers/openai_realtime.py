# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""OpenAIRealtimeTranslationProvider — real provider for v1.

Uses the OpenAI Realtime *Translation* API over WebSocket
(``/v1/realtime/translations`` with the ``gpt-realtime-translate`` model). PCM16
mono audio at 24 kHz is streamed as ``session.input_audio_buffer.append``; the
session is configured with ``audio.output.language`` = the target language, and
the translated text arrives as ``session.output_transcript.delta`` events that
are accumulated into partial/final text. ``session.input_transcript.delta`` (the
source-language transcript) is received only for debug/future use and is never
forwarded downstream.

ALL OpenAI-specific logic lives here: the GUI, the services and vMix know
nothing about the protocol.

Security:
- the API key is read from secure storage (SecretStore), never from config.yaml;
- the key never appears in the logs nor in error messages (headers are never
  logged).

Robustness:
- automatic reconnection with backoff after a dropped connection;
- close() sends ``session.close`` and waits for ``session.closed`` (or a timeout)
  before dropping the socket, and stops the receive task without leaking threads.

The WebSocket connector is injectable to allow network-free tests: tests pass a
fake connector; in production the ``websockets`` library is used.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import Awaitable, Callable

import numpy as np

from app.config.secrets import SecretStore
from app.i18n import t
from app.providers.base import (
    ProviderConfig,
    ProviderError,
    RealtimeTranslationProvider,
)

logger = logging.getLogger("app.providers.openai")

REALTIME_URL = "wss://api.openai.com/v1/realtime/translations"
DEFAULT_REALTIME_MODEL = "gpt-realtime-translate"
# The Realtime WebSocket API expects PCM16 mono at 24 kHz: capture usually runs
# at a lower rate, so audio is resampled here before being sent.
OPENAI_INPUT_SAMPLE_RATE = 24000
MAX_BACKOFF_S = 30.0
# Strictly below the pipeline's outer close budget (pipeline.stop() waits 5 s on
# close()): so close() always returns before that outer timeout can fire.
DEFAULT_CLOSE_TIMEOUT_S = 3.0

# A connector receives (url, headers) and returns a WebSocket object with
# async methods send(str) / recv() -> str / close(). websockets satisfies this
# shape; tests inject a fake.
WebSocketConnector = Callable[[str, dict], Awaitable[object]]

# Event types of the OpenAI Realtime Translation protocol.
OUTPUT_DELTA_TYPE = "session.output_transcript.delta"
OUTPUT_DONE_TYPE = "session.output_transcript.done"
INPUT_DELTA_TYPE = "session.input_transcript.delta"
SESSION_CLOSED_TYPE = "session.closed"


class OpenAIProviderError(ProviderError):
    """Provider error with an operator-readable message (Italian)."""


async def _default_connector(url: str, headers: dict) -> object:
    import websockets

    # websockets >=12 uses additional_headers; earlier versions extra_headers
    try:
        return await websockets.connect(url, additional_headers=headers)
    except TypeError:
        return await websockets.connect(url, extra_headers=headers)


def _resample_pcm16_mono(data: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Linear-resample mono PCM16 bytes from ``src_rate`` to ``dst_rate``.

    OpenAI requires 24 kHz while capture usually runs at 16 kHz. Assumes mono
    little-endian int16; returns the data unchanged when the rates already match
    or the input is too small to resample. Per-chunk linear interpolation is good
    enough for speech at these rates.
    """
    if src_rate == dst_rate or not data:
        return data
    samples = np.frombuffer(data, dtype="<i2")
    if samples.size < 2:
        return data
    dst_len = int(round(samples.size * dst_rate / src_rate))
    if dst_len <= 0:
        return b""
    positions = np.linspace(0.0, samples.size - 1, num=dst_len)
    resampled = np.interp(positions, np.arange(samples.size), samples)
    return np.rint(resampled).astype("<i2").tobytes()


class OpenAIRealtimeTranslationProvider(RealtimeTranslationProvider):
    def __init__(
        self,
        secret_store: SecretStore,
        provider_name: str = "openai",
        model: str = DEFAULT_REALTIME_MODEL,
        connector: WebSocketConnector | None = None,
        close_timeout_s: float = DEFAULT_CLOSE_TIMEOUT_S,
    ) -> None:
        super().__init__()
        self._secret_store = secret_store
        self._provider_name = provider_name
        self._model = model
        self._connector = connector or _default_connector
        self._close_timeout_s = close_timeout_s
        self._config = ProviderConfig()
        self._ws: object | None = None
        self._task: asyncio.Task | None = None
        self._closed = False
        self._closing = False
        self._response_buffer = ""
        # set by the receive loop when the server acknowledges session.close
        self._closed_ack = asyncio.Event()

    # ------------------------------------------------------------------ API

    async def connect(self, config: ProviderConfig) -> None:
        self._config = config
        self._closed = False
        self._closing = False
        self._response_buffer = ""
        self._closed_ack = asyncio.Event()
        api_key = self._load_key()
        # first synchronous connection: if the key is wrong or the network is
        # down, the error propagates immediately to the caller (start_translation shows it)
        ws = await self._open(api_key)
        self._ws = ws
        self._task = asyncio.create_task(self._receive_and_reconnect(api_key))

    async def send_audio(self, chunk: bytes) -> None:
        ws = self._ws
        if ws is None or self._closed:
            return
        audio = self._prepare_audio(chunk)
        if not audio:
            return
        payload = {
            "type": "session.input_audio_buffer.append",
            "audio": base64.b64encode(audio).decode("ascii"),
        }
        try:
            await ws.send(json.dumps(payload))
        except Exception:
            # the drop is handled by the receive/reconnect loop
            logger.debug("Invio audio fallito: connessione non disponibile")

    def _prepare_audio(self, chunk: bytes) -> bytes:
        # OpenAI wants PCM16 MONO @ 24 kHz. Down-mix multichannel input to mono
        # (never pass interleaved audio through) and then resample to 24 kHz.
        if not chunk:
            return chunk
        channels = max(self._config.channels, 1)
        frame = 2 * channels  # bytes per multichannel int16 frame
        if len(chunk) % frame:
            # keep int16/frame alignment: drop any trailing partial frame
            chunk = chunk[: len(chunk) // frame * frame]
            if not chunk:
                return b""
        if channels > 1:
            samples = np.frombuffer(chunk, dtype="<i2").reshape(-1, channels)
            mono = np.rint(samples.mean(axis=1)).astype("<i2").tobytes()
        else:
            mono = chunk
        return _resample_pcm16_mono(
            mono, self._config.sample_rate, OPENAI_INPUT_SAMPLE_RATE
        )

    def request_close(self) -> None:
        # called synchronously by the pipeline before close() is scheduled: mark
        # the stop intent so a socket drop during teardown does not look like a
        # dropped connection (no spurious reconnect / "connection lost").
        self._closing = True

    async def close(self) -> None:
        # ask the server to close, then wait for its session.closed ack (or a
        # timeout) before dropping the socket; the receive loop is still running
        # to observe the ack, so we only flip _closed afterwards.
        self._closing = True
        ws = self._ws
        if ws is not None:
            try:
                await ws.send(json.dumps({"type": "session.close"}))
            except Exception:
                pass
            try:
                await asyncio.wait_for(
                    self._closed_ack.wait(), timeout=self._close_timeout_s
                )
            except TimeoutError:
                logger.debug("session.closed non ricevuto entro il timeout")
        self._closed = True
        task, self._task = self._task, None
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    # ------------------------------------------------------------------ internal

    def _load_key(self) -> str:
        key = self._secret_store.get_api_key(self._provider_name)
        if not key:
            raise OpenAIProviderError(t("openai.no_api_key"))
        return key

    def _headers(self, api_key: str) -> dict:
        return {
            "Authorization": f"Bearer {api_key}",
            "OpenAI-Beta": "realtime=v1",
        }

    def _url(self) -> str:
        return f"{REALTIME_URL}?model={self._model}"

    async def _open(self, api_key: str) -> object:
        try:
            ws = await self._connector(self._url(), self._headers(api_key))
        except Exception as exc:
            raise self._translate_connect_error(exc) from None
        await self._send_session_config(ws)
        return ws

    async def _send_session_config(self, ws: object) -> None:
        # Configure PCM16 input and the output (translation) language. The
        # translate model detects the source language on its own.
        session = {
            "type": "session.update",
            "session": {
                "audio": {
                    "input": {"format": "pcm16"},
                    "output": {"language": self._config.target_language},
                },
            },
        }
        await ws.send(json.dumps(session))

    async def _receive_and_reconnect(self, api_key: str) -> None:
        backoff = 1.0
        try:
            # keep reading while not fully closed: during close() we stay in the
            # loop (only _closing is set) so we can still observe session.closed;
            # _closing then suppresses the reconnect below.
            while not self._closed:
                ws = self._ws
                if ws is None:
                    break
                try:
                    await self._receive_loop(ws)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning(
                        "Connessione OpenAI interrotta: %s", type(exc).__name__
                    )
                # intentional close: do not treat it as a drop / do not reconnect.
                # unblock close(): if the socket dropped without a session.closed
                # frame, no ack will ever arrive, so release the waiter now.
                if self._closed or self._closing:
                    self._closed_ack.set()
                    break
                # connection dropped: notify and retry with backoff
                self._emit_error(t("provider.connection_lost"))
                self._ws = None
                await asyncio.sleep(min(backoff, MAX_BACKOFF_S))
                backoff = min(backoff * 2, MAX_BACKOFF_S)
                try:
                    self._ws = await self._open(api_key)
                    backoff = 1.0
                except asyncio.CancelledError:
                    raise
                except OpenAIProviderError:
                    continue  # will retry on the next round
        except asyncio.CancelledError:
            pass

    async def _receive_loop(self, ws: object) -> None:
        while not self._closed:
            raw = await ws.recv()
            if raw is None:
                return
            self._handle_message(raw)

    def _handle_message(self, raw: str | bytes) -> None:
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            logger.debug("Messaggio OpenAI non JSON ignorato")
            return
        event_type = data.get("type", "")
        if event_type == OUTPUT_DELTA_TYPE:
            self._response_buffer += data.get("delta", "")
            if self._response_buffer:
                self._emit_partial(self._response_buffer)
        elif event_type == OUTPUT_DONE_TYPE:
            text = data.get("transcript") or self._response_buffer
            if text:
                self._emit_final(text)
            self._response_buffer = ""
        elif event_type == INPUT_DELTA_TYPE:
            # source-language transcript: debug/future only, never sent to vMix
            logger.debug("Trascrizione sorgente ricevuta (delta)")
        elif event_type == SESSION_CLOSED_TYPE:
            self._closed_ack.set()
        elif event_type == "error":
            self._emit_error(self._error_message(data))

    @staticmethod
    def _error_message(data: dict) -> str:
        error = data.get("error") or {}
        code = error.get("code", "")
        if code in ("invalid_api_key", "authentication_error"):
            return t("provider.api_key_invalid")
        # OpenAI's raw message may contain technical details: keep
        # a simple text for the operator
        return t("provider.translation_error")

    @staticmethod
    def _translate_connect_error(exc: Exception) -> OpenAIProviderError:
        status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
        text = str(exc)
        if status in (401, 403) or "401" in text or "403" in text:
            return OpenAIProviderError(t("provider.api_key_invalid"))
        return OpenAIProviderError(t("openai.unreachable"))


async def check_api_key(
    secret_store: SecretStore,
    provider_name: str = "openai",
    model: str = DEFAULT_REALTIME_MODEL,
    connector: WebSocketConnector | None = None,
    timeout_s: float = 8.0,
) -> None:
    """Verifies the key by opening a realtime session and closing it immediately.

    It sends no audio, so it does not consume translation tokens. Raises
    OpenAIProviderError with a readable message if the key is missing,
    invalid, or the network is unavailable.
    """
    provider = OpenAIRealtimeTranslationProvider(
        secret_store, provider_name, model=model, connector=connector
    )
    api_key = provider._load_key()
    try:
        ws = await asyncio.wait_for(
            provider._connector(provider._url(), provider._headers(api_key)),
            timeout=timeout_s,
        )
    except TimeoutError as exc:
        raise OpenAIProviderError(t("openai.unreachable")) from exc
    except Exception as exc:
        raise provider._translate_connect_error(exc) from None
    try:
        # a first server event confirms the session was authenticated
        await asyncio.wait_for(ws.recv(), timeout=timeout_s)
    except TimeoutError as exc:
        raise OpenAIProviderError(t("openai.no_response")) from exc
    finally:
        try:
            await ws.close()
        except Exception:
            pass
