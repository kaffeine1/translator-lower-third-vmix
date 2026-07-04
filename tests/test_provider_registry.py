# Translator Lower Third for vMix
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""Provider registry tests (v1.1) — provider selection without network."""

from __future__ import annotations

import pytest

from app.audio.input import FakeAudioInput
from app.config.models import AppConfig
from app.config.secrets import InMemorySecretStore
from app.providers.fake import FakeTranslationProvider
from app.providers.openai_realtime import OpenAIRealtimeTranslationProvider
from app.providers.registry import (
    available_providers,
    create_provider,
    get_provider_info,
)
from app.services import LiveAppServices


def test_registry_lists_openai_and_demo():
    ids = [info.id for info in available_providers()]
    assert "openai" in ids
    assert "fake" in ids


def test_registry_lists_composed_cloud_pipelines():
    ids = [info.id for info in available_providers()]
    assert "google-deepl" in ids
    assert "azure-deepl" in ids


def test_composed_provider_required_keys():
    assert get_provider_info("google-deepl").required_key_names == ("google", "deepl")
    assert get_provider_info("azure-deepl").required_key_names == (
        "azure", "azure-region", "deepl",
    )


def test_composed_provider_credential_fields():
    creds = get_provider_info("azure-deepl").credentials
    accounts = [c.account for c in creds]
    assert accounts == ["azure", "azure-region", "deepl"]
    # region and google path are plain (non-secret) fields
    region = next(c for c in creds if c.account == "azure-region")
    assert region.secret is False


def test_create_composed_cloud_provider():
    from app.providers.composed import ComposedRealtimeProvider

    store = InMemorySecretStore()
    store.set_api_key("google", "/creds.json")
    store.set_api_key("deepl", "k:fx")
    provider = create_provider("google-deepl", store)
    assert isinstance(provider, ComposedRealtimeProvider)


def test_all_credential_accounts():
    from app.providers.registry import all_credential_accounts

    accounts = all_credential_accounts()
    assert {"openai", "google", "azure", "azure-region", "deepl"} <= accounts


def test_make_provider_composed_falls_back_to_demo_without_keys():
    services = _services("google-deepl", with_key=False)
    assert isinstance(services._make_provider(), FakeTranslationProvider)


def test_make_provider_composed_with_all_keys():
    from app.providers.composed import ComposedRealtimeProvider

    store = InMemorySecretStore()
    store.set_api_key("google", "/creds.json")
    store.set_api_key("deepl", "k:fx")
    services = LiveAppServices(FakeAudioInput(), store)
    config = AppConfig()
    config.provider = "google-deepl"
    services.update_config(config)
    assert isinstance(services._make_provider(), ComposedRealtimeProvider)


def test_test_api_composed_missing_keys_is_error():
    services = _services("azure-deepl", with_key=False)
    result = services.test_api()
    assert result.ok is False


def test_test_api_composed_present_keys_ok_without_live_check():
    store = InMemorySecretStore()
    store.set_api_key("azure", "k")
    store.set_api_key("azure-region", "westeurope")
    store.set_api_key("deepl", "d:fx")
    services = LiveAppServices(FakeAudioInput(), store)
    config = AppConfig()
    config.provider = "azure-deepl"
    services.update_config(config)
    result = services.test_api()
    assert result.ok is True
    assert "credenziali" in result.message.lower()


def test_provider_info_flags():
    assert get_provider_info("openai").requires_api_key is True
    assert get_provider_info("fake").requires_api_key is False
    assert get_provider_info("inesistente") is None


def test_create_provider_types():
    assert isinstance(create_provider("fake", None), FakeTranslationProvider)
    store = InMemorySecretStore()
    assert isinstance(
        create_provider("openai", store), OpenAIRealtimeTranslationProvider
    )


def test_create_provider_unknown_raises():
    with pytest.raises(ValueError):
        create_provider("boh", None)


def _services(provider_id: str, with_key: bool):
    store = InMemorySecretStore()
    if with_key:
        store.set_api_key("openai", "sk-test-000000000000")
    services = LiveAppServices(FakeAudioInput(), store)
    config = AppConfig()
    config.provider = provider_id
    services.update_config(config)
    return services


def test_make_provider_demo_selected_even_with_key():
    # explicitly choosing the demo must hold even if there is a key
    services = _services("fake", with_key=True)
    assert isinstance(services._make_provider(), FakeTranslationProvider)


def test_make_provider_openai_with_key():
    services = _services("openai", with_key=True)
    assert isinstance(services._make_provider(), OpenAIRealtimeTranslationProvider)


def test_make_provider_openai_without_key_falls_back_to_demo():
    services = _services("openai", with_key=False)
    assert isinstance(services._make_provider(), FakeTranslationProvider)


def test_make_provider_unknown_falls_back_to_demo():
    services = _services("marziano", with_key=False)
    assert isinstance(services._make_provider(), FakeTranslationProvider)


def test_test_api_demo_ok_without_key():
    services = _services("fake", with_key=False)
    result = services.test_api()
    assert result.ok is True
    assert "demo" in result.message.lower()


def test_test_api_openai_without_key_is_error():
    services = _services("openai", with_key=False)
    result = services.test_api()
    assert result.ok is False
    assert "chiave api" in result.message.lower()


def test_settings_dialog_provider_list_includes_demo():
    from app.gui.settings_dialog import PROVIDERS

    ids = [pid for _label, pid in PROVIDERS]
    assert "openai" in ids
    assert "fake" in ids
