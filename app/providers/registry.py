# Traduttore Live
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
    ``help_key`` is an optional i18n key for a one-line "how to obtain this"
    hint, and ``help_url`` an optional link to the provider console page — the
    GUI shows them under the field so a non-technical operator knows where to get
    the key.
    """

    account: str
    label_key: str
    secret: bool = True
    help_key: str = ""
    help_url: str = ""


# Reusable credential descriptors (one per secure-storage account).
_CRED_OPENAI = CredentialField(
    "openai",
    "cred.openai_key",
    help_key="cred_help.openai",
    help_url="https://platform.openai.com/api-keys",
)
_CRED_DEEPL = CredentialField(
    "deepl",
    "cred.deepl_key",
    help_key="cred_help.deepl",
    help_url="https://www.deepl.com/pro-api",
)
_CRED_GOOGLE = CredentialField(
    "google",
    "cred.google_credentials",
    secret=False,
    help_key="cred_help.google",
    help_url="https://console.cloud.google.com/iam-admin/serviceaccounts/create",
)
# Google Cloud Translation (v2 REST) uses an API key, distinct from the service
# account JSON that Google Speech uses.
_CRED_GOOGLE_TRANSLATE = CredentialField(
    "google-translate",
    "cred.google_translate_key",
    help_key="cred_help.google_translate",
    help_url="https://console.cloud.google.com/apis/credentials",
)
_CRED_AZURE = CredentialField(
    "azure",
    "cred.azure_key",
    help_key="cred_help.azure",
    help_url="https://portal.azure.com/#create/Microsoft.CognitiveServicesAllInOne",
)
_CRED_AZURE_REGION = CredentialField(
    "azure-region", "cred.azure_region", secret=False, help_key="cred_help.azure_region"
)


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
    "google-google": ProviderInfo(
        "google-google",
        "Google Speech → Google Translate",
        (_CRED_GOOGLE, _CRED_GOOGLE_TRANSLATE),
    ),
    "azure-azure": ProviderInfo(
        "azure-azure",
        "Azure Speech → Azure Translator",
        (_CRED_AZURE, _CRED_AZURE_REGION),
    ),
    # local (offline) pipeline: no credentials, needs the optional local packages
    "local": ProviderInfo("local", "Locale (Faster-Whisper → MarianMT)"),
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
    provider_id: str, secret_store: SecretStore | None, config: object | None = None
) -> RealtimeTranslationProvider:
    """Instantiates the requested realtime provider. Lazy import: heavy modules
    (OpenAI/websockets, cloud/local SDKs) load only if they are actually needed.
    ``config`` (an AppConfig) supplies local-provider options (model/device)."""
    if provider_id == "fake":
        from app.providers.fake import FakeTranslationProvider

        return FakeTranslationProvider()
    if provider_id == "demo-composed":
        from app.providers.composed import make_demo_composed_provider

        return make_demo_composed_provider()
    if provider_id == "openai":
        from app.providers.openai_realtime import OpenAIRealtimeTranslationProvider

        return OpenAIRealtimeTranslationProvider(secret_store, "openai")
    if provider_id == "google-google":
        return create_composed_provider("google", "google-translate", secret_store)
    if provider_id == "azure-azure":
        return create_composed_provider("azure", "azure-translator", secret_store)
    if provider_id == "local":
        return create_composed_provider("faster-whisper", "marian", secret_store, config)
    raise ValueError(f"Provider sconosciuto: {provider_id}")


# --------------------------------------------------------------------------- #
# SpeechProvider (audio → source text): used INSIDE a composed provider together
# with a TranslationProvider. They do not appear in the realtime GUI selector.
# --------------------------------------------------------------------------- #

_SPEECH_REGISTRY: dict[str, ProviderInfo] = {
    "fake-speech": ProviderInfo("fake-speech", "Demo (voce)"),
    "google": ProviderInfo("google", "Google Speech-to-Text", (_CRED_GOOGLE,)),
    "azure": ProviderInfo("azure", "Azure Speech", (_CRED_AZURE, _CRED_AZURE_REGION)),
    "faster-whisper": ProviderInfo("faster-whisper", "Faster-Whisper (locale)"),
}


def available_speech_providers() -> list[ProviderInfo]:
    return list(_SPEECH_REGISTRY.values())


def get_speech_provider_info(provider_id: str) -> ProviderInfo | None:
    return _SPEECH_REGISTRY.get(provider_id)


def create_speech_provider(
    provider_id: str, secret_store: SecretStore | None, config: object | None = None
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
    if provider_id == "faster-whisper":
        from app.providers.local_whisper import (
            DEFAULT_DEVICE,
            DEFAULT_MODEL,
            FasterWhisperSpeechProvider,
        )

        model = getattr(config, "local_model", None) or DEFAULT_MODEL
        device = getattr(config, "local_device", None) or DEFAULT_DEVICE
        return FasterWhisperSpeechProvider(model=model, device=device)
    raise ValueError(f"Provider vocale sconosciuto: {provider_id}")


def create_composed_provider(
    speech_id: str,
    translation_id: str,
    secret_store: SecretStore | None,
    config: object | None = None,
) -> RealtimeTranslationProvider:
    """Builds a ComposedRealtimeProvider from a SpeechProvider and a
    TranslationProvider (e.g. 'google' + 'deepl', or 'faster-whisper' + 'marian').
    ``config`` (an AppConfig) supplies local-provider options."""
    from app.providers.composed import ComposedRealtimeProvider

    return ComposedRealtimeProvider(
        create_speech_provider(speech_id, secret_store, config),
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
    "google-translate": ProviderInfo(
        "google-translate", "Google Translate", (_CRED_GOOGLE_TRANSLATE,)
    ),
    "azure-translator": ProviderInfo(
        "azure-translator", "Azure Translator", (_CRED_AZURE, _CRED_AZURE_REGION)
    ),
    "marian": ProviderInfo("marian", "MarianMT (locale)"),
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
    if provider_id == "google-translate":
        from app.providers.google_translate import GoogleTranslateProvider

        return GoogleTranslateProvider(secret_store, "google-translate")
    if provider_id == "azure-translator":
        from app.providers.azure_translate import AzureTranslatorProvider

        return AzureTranslatorProvider(secret_store, "azure", "azure-region")
    if provider_id == "marian":
        from app.providers.local_translate import LocalMarianTranslationProvider

        return LocalMarianTranslationProvider()
    raise ValueError(f"Provider di traduzione sconosciuto: {provider_id}")
