# Translator Lower Third for vMix
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""Registry of translation providers (v1.1 base).

A single place where the available providers are declared with id, display
name, and whether they require an API key. The GUI populates the selector from
here and the services create the provider via create_provider(): adding a
future provider (Google, Azure, self-hosted…) means registering it here, without
touching the GUI or services.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config.secrets import SecretStore
from app.providers.base import (
    RealtimeTranslationProvider,
    SpeechProvider,
    TranslationProvider,
)


@dataclass(frozen=True)
class CredentialField:
    """A credential a provider needs, stored in secure storage under ``account``.

    ``label_key`` is an i18n key for the field label; ``secret`` marks a
    password field (hidden) vs a plain value like a file path or a region.
    """

    account: str
    label_key: str
    secret: bool = True


# Reusable credential descriptors (one per secure-storage account).
_CRED_OPENAI = CredentialField("openai", "cred.openai_key")
_CRED_DEEPL = CredentialField("deepl", "cred.deepl_key")
_CRED_GOOGLE = CredentialField("google", "cred.google_credentials", secret=False)
_CRED_AZURE = CredentialField("azure", "cred.azure_key")
_CRED_AZURE_REGION = CredentialField("azure-region", "cred.azure_region", secret=False)


@dataclass(frozen=True)
class ProviderInfo:
    id: str
    display_name: str
    credentials: tuple[CredentialField, ...] = ()

    @property
    def required_key_names(self) -> tuple[str, ...]:
        return tuple(c.account for c in self.credentials)

    @property
    def requires_api_key(self) -> bool:
        return bool(self.credentials)


# Order = order in the GUI selector (complete realtime providers).
_REGISTRY: dict[str, ProviderInfo] = {
    "openai": ProviderInfo("openai", "OpenAI Realtime", (_CRED_OPENAI,)),
    "fake": ProviderInfo("fake", "Demo (senza API)"),
    "demo-composed": ProviderInfo("demo-composed", "Demo (speech + traduzione separati)"),
    "google-deepl": ProviderInfo(
        "google-deepl", "Google Speech → DeepL", (_CRED_GOOGLE, _CRED_DEEPL)
    ),
    "azure-deepl": ProviderInfo(
        "azure-deepl", "Azure Speech → DeepL", (_CRED_AZURE, _CRED_AZURE_REGION, _CRED_DEEPL)
    ),
}

DEFAULT_PROVIDER_ID = "openai"


def available_providers() -> list[ProviderInfo]:
    return list(_REGISTRY.values())


def all_credential_accounts() -> set[str]:
    """Union of every secure-storage account used by any realtime provider."""
    accounts: set[str] = set()
    for info in _REGISTRY.values():
        accounts.update(info.required_key_names)
    return accounts


def get_provider_info(provider_id: str) -> ProviderInfo | None:
    return _REGISTRY.get(provider_id)


def create_provider(
    provider_id: str, secret_store: SecretStore | None
) -> RealtimeTranslationProvider:
    """Instantiates the requested realtime provider. Lazy import: heavy modules
    (OpenAI/websockets, cloud SDKs) load only if they are actually needed."""
    if provider_id == "fake":
        from app.providers.fake import FakeTranslationProvider

        return FakeTranslationProvider()
    if provider_id == "demo-composed":
        from app.providers.composed import make_demo_composed_provider

        return make_demo_composed_provider()
    if provider_id == "openai":
        from app.providers.openai_realtime import OpenAIRealtimeTranslationProvider

        return OpenAIRealtimeTranslationProvider(secret_store, "openai")
    if provider_id == "google-deepl":
        return create_composed_provider("google", "deepl", secret_store)
    if provider_id == "azure-deepl":
        return create_composed_provider("azure", "deepl", secret_store)
    raise ValueError(f"Provider sconosciuto: {provider_id}")


# --------------------------------------------------------------------------- #
# SpeechProvider (audio → source text): used INSIDE a composed provider together
# with a TranslationProvider. They do not appear in the realtime GUI selector.
# --------------------------------------------------------------------------- #

_SPEECH_REGISTRY: dict[str, ProviderInfo] = {
    "fake-speech": ProviderInfo("fake-speech", "Demo (voce)"),
    "google": ProviderInfo("google", "Google Speech-to-Text", (_CRED_GOOGLE,)),
    "azure": ProviderInfo("azure", "Azure Speech", (_CRED_AZURE, _CRED_AZURE_REGION)),
}


def available_speech_providers() -> list[ProviderInfo]:
    return list(_SPEECH_REGISTRY.values())


def get_speech_provider_info(provider_id: str) -> ProviderInfo | None:
    return _SPEECH_REGISTRY.get(provider_id)


def create_speech_provider(
    provider_id: str, secret_store: SecretStore | None
) -> SpeechProvider:
    if provider_id == "fake-speech":
        from app.providers.composed import FakeSpeechProvider

        return FakeSpeechProvider()
    if provider_id == "google":
        from app.providers.google_speech import GoogleSpeechProvider

        return GoogleSpeechProvider(secret_store, "google")
    if provider_id == "azure":
        from app.providers.azure_speech import AzureSpeechProvider

        return AzureSpeechProvider(secret_store, "azure")
    raise ValueError(f"Provider vocale sconosciuto: {provider_id}")


def create_composed_provider(
    speech_id: str, translation_id: str, secret_store: SecretStore | None
) -> RealtimeTranslationProvider:
    """Builds a ComposedRealtimeProvider from a SpeechProvider and a
    TranslationProvider (e.g. 'google' + 'deepl'). It is the programmatic way to
    combine cloud providers; wiring it into the GUI (with multiple credentials)
    will come in a later increment."""
    from app.providers.composed import ComposedRealtimeProvider

    return ComposedRealtimeProvider(
        create_speech_provider(speech_id, secret_store),
        create_translation_provider(translation_id, secret_store),
    )


# --------------------------------------------------------------------------- #
# TranslationProvider (text only): used INSIDE a ComposedRealtimeProvider,
# together with a SpeechProvider. They do not appear in the realtime provider
# GUI selector because on their own they do not produce subtitles.
# --------------------------------------------------------------------------- #

_TRANSLATION_REGISTRY: dict[str, ProviderInfo] = {
    "fake-text": ProviderInfo("fake-text", "Demo (traduzione testo)"),
    "deepl": ProviderInfo("deepl", "DeepL", (_CRED_DEEPL,)),
}


def available_translation_providers() -> list[ProviderInfo]:
    return list(_TRANSLATION_REGISTRY.values())


def get_translation_provider_info(provider_id: str) -> ProviderInfo | None:
    return _TRANSLATION_REGISTRY.get(provider_id)


def create_translation_provider(
    provider_id: str, secret_store: SecretStore | None
) -> TranslationProvider:
    if provider_id == "fake-text":
        from app.providers.composed import FakeTranslationTextProvider

        return FakeTranslationTextProvider()
    if provider_id == "deepl":
        from app.providers.deepl import DeepLTranslationProvider

        return DeepLTranslationProvider(secret_store, "deepl")
    raise ValueError(f"Provider di traduzione sconosciuto: {provider_id}")
