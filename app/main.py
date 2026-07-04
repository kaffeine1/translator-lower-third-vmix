# Translator Lower Third for vMix
# Autore: Michele Dipace <michele.dipace@kaffeine.net>
"""Application entry point: config + logging bootstrap, then the PySide6 GUI.

Milestone 2: i pulsanti sono collegati a MockAppServices (nessuna chiamata
reale ad audio, provider o vMix).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from app import APP_DISPLAY_NAME, APP_NAME, __version__
from app.audio.input import SoundDeviceAudioInput
from app.config.manager import ConfigManager
from app.config.secrets import KeyringSecretStore, SecretStorageError
from app.logging.setup import setup_logging
from app.services import LiveAppServices


def _icon_path() -> Path | None:
    """Percorso di assets/icon.ico, sia in sviluppo sia nel pacchetto PyInstaller."""
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

    # Audio (M3), vMix (M4) e provider OpenAI (M7) reali; senza chiave salvata
    # il provider ricade sulla demo finta
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
                    "Impossibile salvare la configurazione su disco. "
                    "Potrai riprovare dal pulsante Impostazioni.",
                )
            key = wizard.entered_api_key()
            if key:
                try:
                    secret_store.set_api_key(config.provider, key)
                except SecretStorageError as exc:
                    QMessageBox.warning(None, APP_DISPLAY_NAME, str(exc))
        # wizard annullato: nessun salvataggio, così ricompare al prossimo avvio

    window = MainWindow(manager, config, services, secret_store)
    window.show()

    if manager.load_warning:
        QMessageBox.warning(window, APP_DISPLAY_NAME, manager.load_warning)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
