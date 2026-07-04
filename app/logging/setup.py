# Translator Lower Third for vMix
# Autore: Michele Dipace <michele.dipace@kaffeine.net>
"""Rotating log files with secret masking.

Layout under %LOCALAPPDATA%\\TranslatorLowerThird\\logs\\:

    app.log       everything under the "app" logger tree
    provider.log  app.providers.* only
    vmix.log      app.outputs.* only

Every handler carries a SecretMaskingFilter so API-key-shaped strings can never
reach disk, whatever module logged them. Raw audio and full provider payloads
must not be logged at all.
"""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config.manager import get_log_dir

MAX_BYTES = 1_000_000
BACKUP_COUNT = 5

# OpenAI-style keys (sk-..., sk-proj-...)
_SK_KEY = re.compile(r"sk-[A-Za-z0-9_\-]{8,}")
# "Bearer <token>" — masked before the generic pattern so the token itself
# is caught even inside "Authorization: Bearer <token>"
_BEARER = re.compile(r"(?i)\bbearer\s+\S+")
# generic assignments: api_key=..., token: ..., password=..., authorization: ...
_KEY_VALUE = re.compile(
    r"(?i)\b(api[_-]?key|apikey|token|secret|password|authorization)\b(\s*[=:]\s*)(\S+)"
)

_MANAGED_LOGGERS = ("app", "app.providers", "app.outputs")


def redact_secrets(text: str) -> str:
    text = _SK_KEY.sub("***", text)
    text = _BEARER.sub("Bearer ***", text)
    text = _KEY_VALUE.sub(lambda m: f"{m.group(1)}{m.group(2)}***", text)
    return text


# Formatter usato solo per pre-renderizzare i traceback nel filtro
_EXC_FORMATTER = logging.Formatter()


class SecretMaskingFilter(logging.Filter):
    """Rewrites each record so the formatted output contains no secrets.

    Covers the message AND the exception traceback/stack info: the stdlib
    Formatter appends formatException() after the message, so exc_text must be
    pre-rendered and redacted here or a logger.exception() call could write a
    raw key (e.g. from an HTTP error string) to disk.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = redact_secrets(message)
        if redacted != message:
            record.msg = redacted
            record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = _EXC_FORMATTER.formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact_secrets(record.exc_text)
        if record.stack_info:
            record.stack_info = redact_secrets(record.stack_info)
        return True


def _make_handler(path: Path, level: int) -> RotatingFileHandler:
    handler = RotatingFileHandler(
        path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
    )
    handler.addFilter(SecretMaskingFilter())
    return handler


def setup_logging(log_dir: Path | None = None, level: int = logging.INFO) -> Path:
    """Configure rotating logs. Returns the log directory. Safe to call twice."""
    log_dir = Path(log_dir) if log_dir else get_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)

    shutdown_logging()

    app_logger = logging.getLogger("app")
    app_logger.setLevel(level)
    app_logger.addHandler(_make_handler(log_dir / "app.log", level))

    provider_logger = logging.getLogger("app.providers")
    provider_logger.addHandler(_make_handler(log_dir / "provider.log", level))

    vmix_logger = logging.getLogger("app.outputs")
    vmix_logger.addHandler(_make_handler(log_dir / "vmix.log", level))

    return log_dir


def shutdown_logging() -> None:
    """Close and detach all managed handlers (needed for clean test teardown)."""
    for name in _MANAGED_LOGGERS:
        logger = logging.getLogger(name)
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
