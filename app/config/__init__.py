# Translator Lower Third for vMix
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""Configuration: models, manager, and secure secret storage."""

from app.config.manager import ConfigManager, get_config_dir, get_log_dir
from app.config.models import AppConfig, AudioConfig, SubtitleConfig, VmixConfig
from app.config.secrets import (
    InMemorySecretStore,
    KeyringSecretStore,
    SecretStorageError,
    SecretStore,
    mask_secret,
)

__all__ = [
    "AppConfig",
    "AudioConfig",
    "ConfigManager",
    "InMemorySecretStore",
    "KeyringSecretStore",
    "SecretStorageError",
    "SecretStore",
    "SubtitleConfig",
    "VmixConfig",
    "get_config_dir",
    "get_log_dir",
    "mask_secret",
]
