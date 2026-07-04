# Translator Lower Third for vMix
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""OpenAIRealtimeTranslationProvider — real provider for v1.

ALL OpenAI-specific logic lives here: the GUI, the services, and vMix know
nothing about the protocol. It uses the Realtime API over WebSocket: PCM16
audio is sent as input_audio_buffer.append, the model translates the speech
into the target language and returns text (partial deltas + final text) that
become on_partial_text / on_final_text events.

Security:
- the API key is read from secure storage (SecretStore), never from config.yaml;
- the key never appears in the logs nor in error messages (headers are never
  logged).

Robustness:
- automatic reconnection with backoff after a dropped connection;
- close() stops the receive task without leaving tasks/threads hanging.

The WebSocket connector is injectable to allow network-free tests: tests pass
a fake connector; in production the ``websockets`` library is used.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import Awaitable, Callable

from app.config.secrets import SecretStore
from app.i18n import t
from app.providers.base import ProviderConfig, RealtimeTranslationProvider

logger = logging.getLogger("app.providers.openai")

REALTIME_URL = "wss://api.openai.com/v1/realtime"
DEFAULT_REALTIME_MODEL = "gpt-4o-realtime-preview"
MAX_BACKOFF_S = 30.0

# A connector receives (url, headers) and returns a WebSocket object with
# async methods send(str) / recv() -> str / close(). websockets satisfies this
# shape; tests inject a fake.
WebSocketConnector = Callable[[str, dict], Awaitable[object]]

_TEXT_DELTA_TYPES = {"response.text.delta", "response.output_text.delta"}
_TEXT_DONE_TYPES = {"response.text.done", "response.output_text.done"}
_RESPONSE_START_TYPES = {"response.created"}


class OpenAIProviderError(Exception):
    """Provider error with an operator-readable message (Italian)."""


async def _default_connector(url: str, headers: dict) -> object:
    import websockets

    # websockets >=12 uses additional_headers; earlier versions extra_headers
    try:
        return await websockets.connect(url, additional_headers=headers)
    except TypeError:
        return await websockets.connect(url, extra_headers=headers)


def _translation_instructions(source: str, target: str) -> str:
    return (
        f"You are a professional live interpreter. Translate the user's speech "
        f"from {source} to {target}. Output ONLY the translation in {target}, "
        f"with no explanations, no source text, and no quotation marks."
    )


class OpenAIRealtimeTranslationProvider(RealtimeTranslationProvider):
    def __init__(
        self,
        secret_store: SecretStore,
        provider_name: str = "openai",
        model: str = DEFAULT_REALTIME_MODEL,
        connector: WebSocketConnector | None = None,
    ) -> None:
        super().__init__()
        self._secret_store = secret_store
        self._provider_name = provider_name
        self._model = model
        self._connector = connector or _default_connector
        self._config = ProviderConfig()
        self._ws: object | None = None
        self._task: asyncio.Task | None = None
        self._closed = False
        self._response_buffer = ""

    # ------------------------------------------------------------------ API

    async def connect(self, config: ProviderConfig) -> None:
        self._config = config
        self._closed = False
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
        payload = {
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(chunk).decode("ascii"),
        }
        try:
            await ws.send(json.dumps(payload))
        except Exception:
            # the drop is handled by the receive/reconnect loop
            logger.debug("Invio audio fallito: connessione non disponibile")

    async def close(self) -> None:
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
            raise OpenAIProviderError(
                t("openai.no_api_key")
            )
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
        session = {
            "type": "session.update",
            "session": {
                "modalities": ["text"],
                "instructions": _translation_instructions(
                    self._config.source_language, self._config.target_language
                ),
                "input_audio_format": "pcm16",
                "turn_detection": {"type": "server_vad", "create_response": True},
            },
        }
        await ws.send(json.dumps(session))

    async def _receive_and_reconnect(self, api_key: str) -> None:
        backoff = 1.0
        try:
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
                if self._closed:
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
        if event_type in _RESPONSE_START_TYPES:
            self._response_buffer = ""
        elif event_type in _TEXT_DELTA_TYPES:
            self._response_buffer += data.get("delta", "")
            if self._response_buffer:
                self._emit_partial(self._response_buffer)
        elif event_type in _TEXT_DONE_TYPES:
            text = data.get("text") or self._response_buffer
            if text:
                self._emit_final(text)
            self._response_buffer = ""
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
        return OpenAIProviderError(
            t("openai.unreachable")
        )


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
        raise OpenAIProviderError(
            t("openai.unreachable")
        ) from exc
    except Exception as exc:
        raise provider._translate_connect_error(exc) from None
    try:
        # a first response (session.created) confirms authentication
        await asyncio.wait_for(ws.recv(), timeout=timeout_s)
    except TimeoutError as exc:
        raise OpenAIProviderError(
            t("openai.no_response")
        ) from exc
    finally:
        try:
            await ws.close()
        except Exception:
            pass
