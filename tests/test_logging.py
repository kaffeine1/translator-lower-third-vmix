# Translator Lower Third for vMix
# Autore: Michele Dipace <michele.dipace@kaffeine.net>
"""Tests for rotating log setup and secret masking in logs."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

import pytest

from app.logging.setup import redact_secrets, setup_logging, shutdown_logging


@pytest.fixture()
def log_dir(tmp_path):
    yield setup_logging(log_dir=tmp_path)
    shutdown_logging()


def test_setup_creates_log_files(log_dir):
    logging.getLogger("app").info("messaggio generale")
    logging.getLogger("app.providers.fake").info("evento provider")
    logging.getLogger("app.outputs.vmix").info("evento vmix")
    shutdown_logging()  # flush + close

    assert "messaggio generale" in (log_dir / "app.log").read_text(encoding="utf-8")
    assert "evento provider" in (log_dir / "provider.log").read_text(encoding="utf-8")
    assert "evento vmix" in (log_dir / "vmix.log").read_text(encoding="utf-8")


def test_child_logs_also_reach_app_log(log_dir):
    logging.getLogger("app.providers.fake").info("propagato")
    shutdown_logging()
    assert "propagato" in (log_dir / "app.log").read_text(encoding="utf-8")


def test_handlers_are_rotating(log_dir):
    handlers = logging.getLogger("app").handlers
    assert handlers
    assert all(isinstance(h, RotatingFileHandler) for h in handlers)
    assert all(h.backupCount > 0 for h in handlers)


def test_setup_twice_does_not_duplicate_handlers(tmp_path):
    setup_logging(log_dir=tmp_path)
    setup_logging(log_dir=tmp_path)
    try:
        assert len(logging.getLogger("app").handlers) == 1
    finally:
        shutdown_logging()


def test_api_keys_never_reach_log_file(log_dir):
    logger = logging.getLogger("app")
    logger.info("chiave ricevuta sk-proj-verysecretkey1234567890")
    logger.info("api_key=SEGRETISSIMO123 usata per la connessione")
    logger.error("header Authorization: Bearer TOKENSEGRETO999")
    shutdown_logging()

    text = (log_dir / "app.log").read_text(encoding="utf-8")
    assert "verysecretkey" not in text
    assert "SEGRETISSIMO123" not in text
    assert "TOKENSEGRETO999" not in text
    assert "***" in text


def test_exception_tracebacks_are_masked(log_dir):
    # regressione: logger.exception non deve scrivere su disco il testo
    # dell'eccezione in chiaro se contiene una chiave
    logger = logging.getLogger("app")
    try:
        raise RuntimeError("provider refused: api_key=SEGRETO999XYZ non valida")
    except RuntimeError:
        logger.exception("errore dal provider")
    try:
        raise ValueError("bad auth sk-abcdef123456789012345")
    except ValueError:
        logger.exception("errore di autenticazione")
    shutdown_logging()

    text = (log_dir / "app.log").read_text(encoding="utf-8")
    assert "SEGRETO999XYZ" not in text
    assert "sk-abcdef" not in text
    assert "RuntimeError" in text  # il traceback resta, senza segreti
    assert "Traceback" in text


def test_redact_secrets_patterns():
    assert "sk-" not in redact_secrets("key: sk-abcdef123456789")
    assert "hunter2" not in redact_secrets("password=hunter2")
    assert "xyz" not in redact_secrets("Bearer xyz")
    # normal operator text passes through untouched
    normal = "vMix non raggiungibile su 127.0.0.1:8088"
    assert redact_secrets(normal) == normal
