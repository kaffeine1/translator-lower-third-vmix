# Translator Lower Third for vMix
# Autore: Michele Dipace <michele.dipace@kaffeine.net>
"""OpenAIRealtimeTranslationProvider — provider reale per la v1.

TUTTA la logica specifica di OpenAI vive qui: la GUI, i servizi e vMix non
sanno nulla del protocollo. Usa la Realtime API via WebSocket: l'audio PCM16
viene inviato come input_audio_buffer.append, il modello traduce il parlato
nella lingua di destinazione e restituisce testo (delta parziali + testo
finale) che diventano eventi on_partial_text / on_final_text.

Sicurezza:
- la API key è letta da secure storage (SecretStore), mai da config.yaml;
- la key non compare mai nei log né nei messaggi d'errore (gli header non
  vengono mai loggati).

Robustezza:
- riconnessione automatica con backoff dopo una caduta di connessione;
- close() ferma il task di ricezione senza lasciare task/thread appesi.

Il connettore WebSocket è iniettabile per consentire test senza rete: i test
passano un connettore finto; in produzione si usa la libreria ``websockets``.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import Awaitable, Callable

from app.config.secrets import SecretStore
from app.providers.base import ProviderConfig, RealtimeTranslationProvider

logger = logging.getLogger("app.providers.openai")

REALTIME_URL = "wss://api.openai.com/v1/realtime"
DEFAULT_REALTIME_MODEL = "gpt-4o-realtime-preview"
MAX_BACKOFF_S = 30.0

# Un connettore riceve (url, headers) e restituisce un oggetto WebSocket con
# metodi async send(str) / recv() -> str / close(). websockets soddisfa questa
# forma; i test iniettano un finto.
WebSocketConnector = Callable[[str, dict], Awaitable[object]]

_TEXT_DELTA_TYPES = {"response.text.delta", "response.output_text.delta"}
_TEXT_DONE_TYPES = {"response.text.done", "response.output_text.done"}
_RESPONSE_START_TYPES = {"response.created"}


class OpenAIProviderError(Exception):
    """Errore del provider con messaggio leggibile dall'operatore (italiano)."""


async def _default_connector(url: str, headers: dict) -> object:
    import websockets

    # websockets >=12 usa additional_headers; le versioni precedenti extra_headers
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
        # prima connessione sincrona: se la key è errata o la rete è giù,
        # l'errore risale subito a chi avvia (start_translation lo mostra)
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
            # la caduta viene gestita dal loop di ricezione/riconnessione
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

    # ------------------------------------------------------------------ interno

    def _load_key(self) -> str:
        key = self._secret_store.get_api_key(self._provider_name)
        if not key:
            raise OpenAIProviderError(
                "Nessuna chiave API salvata. Inseriscila nelle Impostazioni."
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
                # connessione caduta: avvisa e riprova con backoff
                self._emit_error("Connessione persa, riprovo…")
                self._ws = None
                await asyncio.sleep(min(backoff, MAX_BACKOFF_S))
                backoff = min(backoff * 2, MAX_BACKOFF_S)
                try:
                    self._ws = await self._open(api_key)
                    backoff = 1.0
                except asyncio.CancelledError:
                    raise
                except OpenAIProviderError:
                    continue  # riproverà al giro successivo
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
            return "API key non valida"
        # il messaggio grezzo di OpenAI può contenere dettagli tecnici: teniamo
        # un testo semplice per l'operatore
        return "Errore dal provider di traduzione"

    @staticmethod
    def _translate_connect_error(exc: Exception) -> OpenAIProviderError:
        status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
        text = str(exc)
        if status in (401, 403) or "401" in text or "403" in text:
            return OpenAIProviderError("API key non valida")
        return OpenAIProviderError(
            "Impossibile raggiungere OpenAI. Controlla la connessione Internet."
        )


async def check_api_key(
    secret_store: SecretStore,
    provider_name: str = "openai",
    model: str = DEFAULT_REALTIME_MODEL,
    connector: WebSocketConnector | None = None,
    timeout_s: float = 8.0,
) -> None:
    """Verifica la chiave aprendo una sessione realtime e chiudendola subito.

    Non invia audio, quindi non consuma token di traduzione. Solleva
    OpenAIProviderError con messaggio leggibile in caso di key mancante,
    non valida o rete assente.
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
            "Impossibile raggiungere OpenAI. Controlla la connessione Internet."
        ) from exc
    except Exception as exc:
        raise provider._translate_connect_error(exc) from None
    try:
        # una prima risposta (session.created) conferma l'autenticazione
        await asyncio.wait_for(ws.recv(), timeout=timeout_s)
    except TimeoutError as exc:
        raise OpenAIProviderError(
            "OpenAI non ha risposto in tempo. Riprova."
        ) from exc
    finally:
        try:
            await ws.close()
        except Exception:
            pass
