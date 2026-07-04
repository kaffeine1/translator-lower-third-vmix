# Translator Lower Third for vMix
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""DeepLTranslationProvider — text translation via the DeepL REST API (v1.2).

It is a TranslationProvider: it translates source text → target. It must be used
inside a ComposedRealtimeProvider together with a SpeechProvider (audio → text).
On its own it does not produce subtitles: it needs a text source (later in v1.2:
Google/Azure Speech).

Security: the DeepL key is read from secure storage (provider name "deepl") and
never appears in the logs. The HTTP client is injectable for tests (no real
call by default).
"""

from __future__ import annotations

import logging

import httpx

from app.config.secrets import SecretStore
from app.providers.base import ProviderConfig, TranslationProvider

logger = logging.getLogger("app.providers.deepl")

DEFAULT_TIMEOUT_S = 5.0


class DeepLError(Exception):
    """DeepL error with an operator-readable message (Italian)."""


def _lang(code: str) -> str:
    # DeepL uses uppercase language codes (ES, IT, EN…)
    return (code or "").upper()


class DeepLTranslationProvider(TranslationProvider):
    def __init__(
        self,
        secret_store: SecretStore | None,
        provider_name: str = "deepl",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._secret_store = secret_store
        self._provider_name = provider_name
        self._client = client
        self._owns_client = client is None
        self._base_url = "https://api.deepl.com"
        self._headers: dict[str, str] = {}
        self._source = "ES"
        self._target = "IT"

    @staticmethod
    def base_url_for_key(key: str) -> str:
        # free-plan keys end with ":fx"
        return "https://api-free.deepl.com" if key.endswith(":fx") else "https://api.deepl.com"

    async def connect(self, config: ProviderConfig) -> None:
        self._source = _lang(config.source_language)
        self._target = _lang(config.target_language)
        key = self._secret_store.get_api_key(self._provider_name) if self._secret_store else None
        if not key:
            raise DeepLError(
                "Nessuna chiave DeepL salvata. Inseriscila nelle Impostazioni."
            )
        self._base_url = self.base_url_for_key(key)
        self._headers = {"Authorization": f"DeepL-Auth-Key {key}"}
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_S)

    async def translate(self, text: str) -> str:
        if not text.strip():
            return ""
        if self._client is None:
            raise DeepLError("Provider DeepL non connesso")
        try:
            response = await self._client.post(
                f"{self._base_url}/v2/translate",
                data={
                    "text": text,
                    "source_lang": self._source,
                    "target_lang": self._target,
                },
                headers=self._headers,
            )
        except httpx.TransportError as exc:
            logger.warning("DeepL non raggiungibile: %s", type(exc).__name__)
            raise DeepLError(
                "Impossibile raggiungere DeepL. Controlla la connessione Internet."
            ) from None
        if response.status_code != 200:
            raise DeepLError(self._status_message(response.status_code))
        try:
            translations = response.json()["translations"]
            return translations[0]["text"]
        except (ValueError, KeyError, IndexError) as exc:
            logger.warning("Risposta DeepL inattesa: %s", type(exc).__name__)
            raise DeepLError("Risposta di DeepL non valida") from None

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def _status_message(status_code: int) -> str:
        if status_code in (401, 403):
            return "Chiave DeepL non valida"
        if status_code == 456:
            return "Quota DeepL esaurita"
        if status_code == 429:
            return "Troppe richieste a DeepL: riprova tra poco"
        return f"DeepL ha risposto con un errore (HTTP {status_code})"
