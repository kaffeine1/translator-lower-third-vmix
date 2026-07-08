# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""GoogleTranslateProvider — text translation via the Google Cloud Translation
API (Basic / v2 REST).

A TranslationProvider: source text → target text. Use it inside a
ComposedRealtimeProvider together with a SpeechProvider (e.g. Google Speech).
Kept as a plain REST call over httpx (like the DeepL provider) so it works from
the frozen app without the heavy google-cloud client library.

Auth is an API key (the v2 endpoint accepts an API key; v3/Advanced would need a
service account). The key is read from secure storage (provider name
"google-translate") and never appears in the logs. The HTTP client is injectable
for tests (no real call by default).
"""

from __future__ import annotations

import html
import logging

import httpx

from app.config.secrets import SecretStore
from app.i18n import t
from app.providers.base import ProviderConfig, ProviderError, TranslationProvider

logger = logging.getLogger("app.providers.google_translate")

DEFAULT_TIMEOUT_S = 5.0
_ENDPOINT = "https://translation.googleapis.com/language/translate/v2"


class GoogleTranslateError(ProviderError):
    """Google Translate error with an operator-readable message (Italian)."""


def _lang(code: str) -> str:
    # Google uses lowercase ISO-639-1 codes (es, it, en…)
    return (code or "").lower()


class GoogleTranslateProvider(TranslationProvider):
    def __init__(
        self,
        secret_store: SecretStore | None,
        provider_name: str = "google-translate",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._secret_store = secret_store
        self._provider_name = provider_name
        self._client = client
        self._owns_client = client is None
        self._key = ""
        self._source = "es"
        self._target = "it"

    async def connect(self, config: ProviderConfig) -> None:
        self._source = _lang(config.source_language)
        self._target = _lang(config.target_language)
        key = self._secret_store.get_api_key(self._provider_name) if self._secret_store else None
        if not key:
            raise GoogleTranslateError(t("google_translate.no_api_key"))
        self._key = key
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_S)

    async def translate(self, text: str) -> str:
        if not text.strip():
            return ""
        if self._client is None:
            raise GoogleTranslateError(t("google_translate.not_connected"))
        try:
            response = await self._client.post(
                _ENDPOINT,
                params={"key": self._key},
                json={
                    "q": [text],
                    "source": self._source,
                    "target": self._target,
                    # default is "html", which returns HTML entities (&#39; …) —
                    # ask for plain text so the lower-third shows clean characters
                    "format": "text",
                },
            )
        except httpx.TransportError as exc:
            logger.warning("Google Translate non raggiungibile: %s", type(exc).__name__)
            raise GoogleTranslateError(t("google_translate.unreachable")) from None
        if response.status_code != 200:
            raise GoogleTranslateError(self._status_message(response.status_code))
        try:
            translated = response.json()["data"]["translations"][0]["translatedText"]
        except (ValueError, KeyError, IndexError):
            logger.warning("Risposta Google Translate inattesa")
            raise GoogleTranslateError(t("google_translate.invalid_response")) from None
        # defensive: even with format=text, unescape any stray HTML entities
        return html.unescape(translated)

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def _status_message(status_code: int) -> str:
        if status_code == 400:
            return t("google_translate.bad_request")
        if status_code == 403:
            return t("google_translate.forbidden")
        if status_code == 429:
            return t("google_translate.too_many_requests")
        return t("google_translate.http_error", status_code=status_code)
