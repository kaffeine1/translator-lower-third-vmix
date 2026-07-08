# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""AzureTranslatorProvider — text translation via the Azure AI Translator
(Text Translation) REST API v3.0.

A TranslationProvider: source text → target text. Use it inside a
ComposedRealtimeProvider together with a SpeechProvider (e.g. Azure Speech). A
plain REST call over httpx (like the DeepL provider), so it works from the frozen
app without an extra SDK.

Auth reuses the Azure key and region (stored as "azure" / "azure-region"): with a
multi-service Azure AI resource the same key serves both Speech and Translator.
The key is never logged. The HTTP client is injectable for tests.
"""

from __future__ import annotations

import logging

import httpx

from app.config.secrets import SecretStore
from app.i18n import t
from app.providers.base import ProviderConfig, ProviderError, TranslationProvider

logger = logging.getLogger("app.providers.azure_translate")

DEFAULT_TIMEOUT_S = 5.0
_ENDPOINT = "https://api.cognitive.microsofttranslator.com/translate"


class AzureTranslatorError(ProviderError):
    """Azure Translator error with an operator-readable message (Italian)."""


def _lang(code: str) -> str:
    # Azure Translator uses lowercase short codes (es, it, en…)
    return (code or "").lower()


class AzureTranslatorProvider(TranslationProvider):
    def __init__(
        self,
        secret_store: SecretStore | None,
        provider_name: str = "azure",
        region_name: str = "azure-region",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._secret_store = secret_store
        self._provider_name = provider_name
        self._region_name = region_name
        self._client = client
        self._owns_client = client is None
        self._headers: dict[str, str] = {}
        self._source = "es"
        self._target = "it"

    async def connect(self, config: ProviderConfig) -> None:
        self._source = _lang(config.source_language)
        self._target = _lang(config.target_language)
        key = self._secret_store.get_api_key(self._provider_name) if self._secret_store else None
        if not key:
            raise AzureTranslatorError(t("azure_translator.no_key"))
        region = (
            self._secret_store.get_api_key(self._region_name) if self._secret_store else None
        )
        if not region:
            raise AzureTranslatorError(t("azure_translator.no_region"))
        self._headers = {
            "Ocp-Apim-Subscription-Key": key,
            "Ocp-Apim-Subscription-Region": region,
            "Content-Type": "application/json; charset=UTF-8",
        }
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_S)

    async def translate(self, text: str) -> str:
        if not text.strip():
            return ""
        if self._client is None:
            raise AzureTranslatorError(t("azure_translator.not_connected"))
        try:
            response = await self._client.post(
                _ENDPOINT,
                params={"api-version": "3.0", "from": self._source, "to": self._target},
                json=[{"Text": text}],
                headers=self._headers,
            )
        except httpx.TransportError as exc:
            logger.warning("Azure Translator non raggiungibile: %s", type(exc).__name__)
            raise AzureTranslatorError(t("azure_translator.unreachable")) from None
        if response.status_code != 200:
            raise AzureTranslatorError(self._status_message(response.status_code))
        try:
            return response.json()[0]["translations"][0]["text"]
        except (ValueError, KeyError, IndexError):
            logger.warning("Risposta Azure Translator inattesa")
            raise AzureTranslatorError(t("azure_translator.invalid_response")) from None

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def _status_message(status_code: int) -> str:
        if status_code in (401, 403):
            return t("azure_translator.api_key_invalid")
        if status_code == 429:
            return t("azure_translator.too_many_requests")
        return t("azure_translator.http_error", status_code=status_code)
