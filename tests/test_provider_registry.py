# Translator Lower Third for vMix
# Autore: Michele Dipace <michele.dipace@kaffeine.net>
"""Provider registry tests (v1.1) — selezione provider senza rete."""

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
    # scegliere esplicitamente la demo deve valere anche se c'è una chiave
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
