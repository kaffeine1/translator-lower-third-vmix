# Translator Lower Third for vMix
# Autore: Michele Dipace <michele.dipace@kaffeine.net>
"""Registro dei provider di traduzione (base v1.1).

Un unico punto in cui i provider disponibili sono dichiarati con id, nome
visualizzato e se richiedono una chiave API. La GUI popola il selettore da qui
e i servizi creano il provider tramite create_provider(): aggiungere un provider
futuro (Google, Azure, self-hosted…) significa registrarlo qui, senza toccare
GUI o servizi.
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
class ProviderInfo:
    id: str
    display_name: str
    # nomi degli account secure-storage la cui chiave è necessaria; vuoto = nessuna
    required_key_names: tuple[str, ...] = ()

    @property
    def requires_api_key(self) -> bool:
        return bool(self.required_key_names)


# Ordine = ordine nel selettore della GUI (provider realtime completi).
_REGISTRY: dict[str, ProviderInfo] = {
    "openai": ProviderInfo("openai", "OpenAI Realtime", ("openai",)),
    "fake": ProviderInfo("fake", "Demo (senza API)"),
    "demo-composed": ProviderInfo("demo-composed", "Demo (speech + traduzione separati)"),
}

DEFAULT_PROVIDER_ID = "openai"


def available_providers() -> list[ProviderInfo]:
    return list(_REGISTRY.values())


def get_provider_info(provider_id: str) -> ProviderInfo | None:
    return _REGISTRY.get(provider_id)


def create_provider(
    provider_id: str, secret_store: SecretStore | None
) -> RealtimeTranslationProvider:
    """Istanzia il provider realtime richiesto. Import lazy: i moduli pesanti
    (OpenAI/websockets, SDK cloud) si caricano solo se servono davvero."""
    if provider_id == "fake":
        from app.providers.fake import FakeTranslationProvider

        return FakeTranslationProvider()
    if provider_id == "demo-composed":
        from app.providers.composed import make_demo_composed_provider

        return make_demo_composed_provider()
    if provider_id == "openai":
        from app.providers.openai_realtime import OpenAIRealtimeTranslationProvider

        return OpenAIRealtimeTranslationProvider(secret_store, "openai")
    raise ValueError(f"Provider sconosciuto: {provider_id}")


# --------------------------------------------------------------------------- #
# SpeechProvider (audio → testo sorgente): usati DENTRO un composto insieme a
# un TranslationProvider. Non compaiono nel selettore GUI realtime.
# --------------------------------------------------------------------------- #

_SPEECH_REGISTRY: dict[str, ProviderInfo] = {
    "fake-speech": ProviderInfo("fake-speech", "Demo (voce)"),
    "google": ProviderInfo("google", "Google Speech-to-Text", ("google",)),
    "azure": ProviderInfo("azure", "Azure Speech", ("azure",)),
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
    """Costruisce un ComposedRealtimeProvider da uno SpeechProvider e un
    TranslationProvider (es. 'google' + 'deepl'). È la via programmatica per
    combinare provider cloud; il collegamento nella GUI (con più credenziali)
    arriverà in un incremento successivo."""
    from app.providers.composed import ComposedRealtimeProvider

    return ComposedRealtimeProvider(
        create_speech_provider(speech_id, secret_store),
        create_translation_provider(translation_id, secret_store),
    )


# --------------------------------------------------------------------------- #
# TranslationProvider (solo testo): usati DENTRO un ComposedRealtimeProvider,
# insieme a uno SpeechProvider. Non compaiono nel selettore GUI dei provider
# realtime perché da soli non producono sottotitoli.
# --------------------------------------------------------------------------- #

_TRANSLATION_REGISTRY: dict[str, ProviderInfo] = {
    "fake-text": ProviderInfo("fake-text", "Demo (traduzione testo)"),
    "deepl": ProviderInfo("deepl", "DeepL", ("deepl",)),
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
