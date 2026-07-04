# Translator Lower Third for vMix
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""Application entry point: config + logging bootstrap, then the PySide6 GUI.

Milestone 2: the buttons are wired to MockAppServices (no real calls to
audio, provider or vMix).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from app import APP_DISPLAY_NAME, APP_NAME, __version__
from app.audio.input import SoundDeviceAudioInput
from app.config.manager import ConfigManager
from app.config.secrets import KeyringSecretStore, SecretStorageError
from app.i18n import set_locale, t
from app.logging.setup import setup_logging
from app.services import LiveAppServices


def _icon_path() -> Path | None:
    """Path to assets/icon.ico, both in development and in the PyInstaller bundle."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidate = Path(base) / "assets" / "icon.ico"
    else:
        candidate = Path(__file__).resolve().parent.parent / "assets" / "icon.ico"
    return candidate if candidate.exists() else None


def main() -> int:
    setup_logging()
    logger = logging.getLogger("app.main")
    logger.info("%s v%s avviato", APP_DISPLAY_NAME, __version__)

    manager = ConfigManager()
    first_run = not manager.config_path.exists()
    config = manager.load()
    # activate the interface language before building any UI
    set_locale(config.ui_language)

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

    from app.gui.first_run_wizard import FirstRunWizard
    from app.gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setApplicationVersion(__version__)
    icon_path = _icon_path()
    if icon_path is not None:
        app.setWindowIcon(QIcon(str(icon_path)))

    # Real audio (M3), vMix (M4) and OpenAI provider (M7); without a saved key
    # the provider falls back to the fake demo
    secret_store = KeyringSecretStore()
    services = LiveAppServices(SoundDeviceAudioInput(), secret_store)

    if first_run:
        wizard = FirstRunWizard(config, services.list_audio_devices(), services)
        if wizard.exec() == QDialog.DialogCode.Accepted:
            config = wizard.result_config()
            try:
                manager.save(config)
            except OSError:
                logger.exception("Salvataggio configurazione fallito")
                QMessageBox.warning(
                    None,
                    APP_DISPLAY_NAME,
                    t("app.config_save_failed"),
                )
            key = wizard.entered_api_key()
            if key:
                try:
                    secret_store.set_api_key(config.provider, key)
                except SecretStorageError as exc:
                    QMessageBox.warning(None, APP_DISPLAY_NAME, str(exc))
        # wizard cancelled: nothing saved, so it reappears on the next launch

    window = MainWindow(manager, config, services, secret_store)
    window.show()

    if manager.load_warning:
        QMessageBox.warning(window, APP_DISPLAY_NAME, manager.load_warning)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
