# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""Load/save user configuration under Windows user profile paths.

Non-sensitive settings only: config.yaml must never contain API keys.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml

from app import APP_NAME
from app.config.models import AppConfig
from app.i18n import t

logger = logging.getLogger("app.config")

CONFIG_FILE_NAME = "config.yaml"


def get_config_dir() -> Path:
    """%APPDATA%\\TranslatorLowerThird"""
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / APP_NAME


def get_log_dir() -> Path:
    """%LOCALAPPDATA%\\TranslatorLowerThird\\logs"""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / APP_NAME / "logs"


class ConfigManager:
    """Reads and writes config.yaml, recovering from missing or corrupt files.

    After load(), ``load_warning`` holds an operator-readable Italian message if
    the previous config could not be used (None when everything was fine).
    """

    def __init__(self, config_dir: Path | None = None) -> None:
        self.config_dir = Path(config_dir) if config_dir else get_config_dir()
        self.config_path = self.config_dir / CONFIG_FILE_NAME
        self.load_warning: str | None = None

    def load(self) -> AppConfig:
        self.load_warning = None
        if not self.config_path.exists():
            logger.info("Nessuna configurazione trovata, uso i valori predefiniti")
            return AppConfig()
        try:
            raw = self.config_path.read_text(encoding="utf-8")
            data = yaml.safe_load(raw)
        except (OSError, yaml.YAMLError) as exc:
            self._backup_corrupt_file()
            self.load_warning = t("config.load_corrupt")
            logger.warning("Config non leggibile (%s): ripristino predefiniti", type(exc).__name__)
            return AppConfig()
        if data is None:
            return AppConfig()
        return AppConfig.from_dict(data)

    def save(self, config: AppConfig) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        text = yaml.safe_dump(config.to_dict(), sort_keys=False, allow_unicode=True)
        tmp_path = self.config_path.with_suffix(".yaml.tmp")
        tmp_path.write_text(text, encoding="utf-8")
        tmp_path.replace(self.config_path)
        logger.info("Configurazione salvata in %s", self.config_path)

    def _backup_corrupt_file(self) -> None:
        backup = self.config_path.with_suffix(".yaml.bak")
        try:
            backup.unlink(missing_ok=True)
            self.config_path.replace(backup)
            logger.warning("Config danneggiata salvata come %s", backup)
        except OSError:
            logger.error("Impossibile creare il backup della config danneggiata")
