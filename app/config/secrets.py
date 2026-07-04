# Translator Lower Third for vMix
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""Secure API key storage.

Production uses the Windows Credential Manager through the ``keyring`` library.
Tests and development can use InMemorySecretStore. API keys must never appear
in config.yaml, in logs, or in exception messages — use mask_secret() anywhere
a key value could be echoed.
"""

from __future__ import annotations

from typing import Protocol

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from app.i18n import t

SERVICE_NAME = "TranslatorLowerThird"


def mask_secret(value: str | None) -> str:
    """Return a safe display form of a secret, e.g. '***7f2a'."""
    if not value:
        return ""
    if len(value) <= 12:
        return "***"
    return f"***{value[-4:]}"


class SecretStorageError(Exception):
    """Raised when the secure store is unavailable. Never contains key values."""


class SecretStore(Protocol):
    def get_api_key(self, provider: str) -> str | None: ...

    def set_api_key(self, provider: str, value: str) -> None: ...

    def delete_api_key(self, provider: str) -> None: ...


def _account_name(provider: str) -> str:
    return f"{provider}-api-key"


class KeyringSecretStore:
    """Stores API keys in the OS credential vault (Windows Credential Manager)."""

    def get_api_key(self, provider: str) -> str | None:
        try:
            return keyring.get_password(SERVICE_NAME, _account_name(provider))
        except KeyringError as exc:
            raise SecretStorageError(
                t("secrets.read_failed", error=type(exc).__name__)
            ) from None

    def set_api_key(self, provider: str, value: str) -> None:
        if not value:
            raise SecretStorageError(t("secrets.empty_key"))
        try:
            keyring.set_password(SERVICE_NAME, _account_name(provider), value)
        except KeyringError as exc:
            raise SecretStorageError(
                t("secrets.save_failed", error=type(exc).__name__)
            ) from None

    def delete_api_key(self, provider: str) -> None:
        try:
            keyring.delete_password(SERVICE_NAME, _account_name(provider))
        except PasswordDeleteError:
            pass  # already absent — deleting a missing key is not an error
        except KeyringError as exc:
            raise SecretStorageError(
                t("secrets.delete_failed", error=type(exc).__name__)
            ) from None


class InMemorySecretStore:
    """Volatile store for tests and development. Never persists anything."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def get_api_key(self, provider: str) -> str | None:
        return self._store.get(provider)

    def set_api_key(self, provider: str, value: str) -> None:
        if not value:
            raise SecretStorageError(t("secrets.empty_key"))
        self._store[provider] = value

    def delete_api_key(self, provider: str) -> None:
        self._store.pop(provider, None)
