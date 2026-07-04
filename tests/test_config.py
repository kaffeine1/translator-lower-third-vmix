# Translator Lower Third for vMix
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""Tests for ConfigManager, config models, and secret handling."""

from __future__ import annotations

import yaml

import app.config.secrets as secrets_module
from app.config.manager import ConfigManager, get_config_dir, get_log_dir
from app.config.models import AppConfig
from app.config.secrets import (
    InMemorySecretStore,
    KeyringSecretStore,
    SecretStorageError,
    mask_secret,
)

# ---------------------------------------------------------------- defaults


def test_default_config_values():
    config = AppConfig()
    assert config.provider == "openai"
    assert config.source_language == "es"
    assert config.target_language == "it"
    assert config.audio.sample_rate == 16000
    assert config.audio.channels == 1
    assert config.audio.device_id is None
    assert config.vmix.host == "127.0.0.1"
    assert config.vmix.port == 8088
    assert config.vmix.selected_name == "Headline.Text"
    assert config.subtitles.max_chars_per_line == 42
    assert config.subtitles.max_lines == 2
    assert config.subtitles.min_update_interval_ms == 1200
    assert config.subtitles.hold_seconds == 5
    assert config.subtitles.clear_after_silence_seconds == 8


def test_windows_paths_contain_app_name():
    assert "TranslatorLowerThird" in str(get_config_dir())
    assert str(get_log_dir()).endswith("logs")


# ---------------------------------------------------------------- load/save


def test_save_and_load_roundtrip(tmp_path):
    manager = ConfigManager(config_dir=tmp_path)
    config = AppConfig()
    config.vmix.input = "Sottopancia"
    config.vmix.port = 9999
    config.subtitles.max_chars_per_line = 30
    manager.save(config)

    loaded = ConfigManager(config_dir=tmp_path).load()
    assert loaded == config


def test_save_creates_directories(tmp_path):
    nested = tmp_path / "a" / "b"
    manager = ConfigManager(config_dir=nested)
    manager.save(AppConfig())
    assert (nested / "config.yaml").exists()


def test_load_missing_file_returns_defaults(tmp_path):
    manager = ConfigManager(config_dir=tmp_path)
    config = manager.load()
    assert config == AppConfig()
    assert manager.load_warning is None


def test_load_empty_file_returns_defaults(tmp_path):
    (tmp_path / "config.yaml").write_text("", encoding="utf-8")
    manager = ConfigManager(config_dir=tmp_path)
    assert manager.load() == AppConfig()


def test_load_corrupt_yaml_recovers_with_backup(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("{{{: not yaml :]", encoding="utf-8")
    manager = ConfigManager(config_dir=tmp_path)

    config = manager.load()

    assert config == AppConfig()
    assert manager.load_warning is not None
    assert (tmp_path / "config.yaml.bak").exists()
    assert not config_path.exists()


def test_load_partial_config_merges_defaults(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "vmix:\n  port: 8090\n", encoding="utf-8"
    )
    config = ConfigManager(config_dir=tmp_path).load()
    assert config.vmix.port == 8090
    assert config.vmix.host == "127.0.0.1"  # default preserved
    assert config.subtitles.max_lines == 2


def test_load_wrong_types_fall_back_to_defaults(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "provider: 42\naudio: not-a-dict\nvmix:\n  port: 999999\n", encoding="utf-8"
    )
    config = ConfigManager(config_dir=tmp_path).load()
    assert config.provider == "openai"
    assert config.audio.sample_rate == 16000
    assert config.vmix.port == 8088  # out of range → default


def test_saved_yaml_never_contains_api_key(tmp_path):
    manager = ConfigManager(config_dir=tmp_path)
    manager.save(AppConfig())
    text = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    assert "api_key" not in text.lower().replace("-", "_")
    data = yaml.safe_load(text)
    assert set(data) == {
        "provider", "source_language", "target_language", "audio", "vmix", "subtitles",
    }


# ---------------------------------------------------------------- secret masking


def test_mask_secret_hides_value():
    masked = mask_secret("sk-proj-abcdefghijklmnop1234")
    assert "abcdefghijklmnop" not in masked
    assert masked == "***1234"


def test_mask_secret_short_values_fully_hidden():
    assert mask_secret("shortkey") == "***"


def test_mask_secret_empty():
    assert mask_secret("") == ""
    assert mask_secret(None) == ""


# ---------------------------------------------------------------- secret stores


def test_in_memory_store_roundtrip():
    store = InMemorySecretStore()
    assert store.get_api_key("openai") is None
    store.set_api_key("openai", "sk-test-123456789")
    assert store.get_api_key("openai") == "sk-test-123456789"
    store.delete_api_key("openai")
    assert store.get_api_key("openai") is None


def test_in_memory_store_rejects_empty_key():
    store = InMemorySecretStore()
    try:
        store.set_api_key("openai", "")
        raise AssertionError("expected SecretStorageError")
    except SecretStorageError:
        pass


def test_keyring_store_uses_service_and_account(monkeypatch):
    calls = {}

    class FakeKeyring:
        @staticmethod
        def get_password(service, account):
            calls["get"] = (service, account)
            return "sk-stored-value-000000"

        @staticmethod
        def set_password(service, account, value):
            calls["set"] = (service, account, value)

        @staticmethod
        def delete_password(service, account):
            calls["delete"] = (service, account)

    monkeypatch.setattr(secrets_module, "keyring", FakeKeyring)
    store = KeyringSecretStore()

    store.set_api_key("openai", "sk-new-value-11111111")
    assert calls["set"] == (
        "TranslatorLowerThird", "openai-api-key", "sk-new-value-11111111",
    )
    assert store.get_api_key("openai") == "sk-stored-value-000000"
    assert calls["get"] == ("TranslatorLowerThird", "openai-api-key")
    store.delete_api_key("openai")
    assert calls["delete"] == ("TranslatorLowerThird", "openai-api-key")


def test_keyring_store_error_message_contains_no_secret(monkeypatch):
    import keyring.errors

    class BrokenKeyring:
        @staticmethod
        def set_password(service, account, value):
            raise keyring.errors.KeyringError("vault unavailable")

    monkeypatch.setattr(secrets_module, "keyring", BrokenKeyring)
    store = KeyringSecretStore()
    try:
        store.set_api_key("openai", "sk-supersecret-99999999")
        raise AssertionError("expected SecretStorageError")
    except SecretStorageError as exc:
        assert "sk-supersecret" not in str(exc)
