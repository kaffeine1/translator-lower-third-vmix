# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""Application entry point: config + logging bootstrap, then the PySide6 GUI.

Milestone 2: the buttons are wired to MockAppServices (no real calls to
audio, provider or vMix).
"""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

from app import APP_DISPLAY_NAME, APP_NAME, __version__
from app.audio.input import SystemAudioInput
from app.config.manager import ConfigManager
from app.config.secrets import KeyringSecretStore
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


def _install_crash_diagnostics() -> None:
    """Capture the Python stack of native crashes and uncaught exceptions.

    PySide6 6.x can abort the process on a native fault or an unhandled slot
    exception with no console (pythonw). faulthandler writes the faulting stack
    of every thread to crash.log, and the excepthook logs uncaught exceptions,
    so a crash leaves a readable trace instead of vanishing.
    """
    import faulthandler

    from app.config.manager import get_log_dir

    try:
        log_dir = get_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        # kept open for the whole process lifetime (faulthandler writes on fault)
        crash_file = open(log_dir / "crash.log", "a", encoding="utf-8")  # noqa: SIM115
        faulthandler.enable(file=crash_file, all_threads=True)
    except Exception:
        logging.getLogger("app.main").warning("faulthandler non attivabile")

    def _flush_logs() -> None:
        # a native abort can follow immediately: flush so the trace is on disk
        for handler in logging.getLogger().handlers:
            try:
                handler.flush()
            except Exception:
                pass

    def _log_uncaught(exc_type, exc, tb) -> None:
        logging.getLogger("app.main").critical(
            "Eccezione non gestita", exc_info=(exc_type, exc, tb)
        )
        _flush_logs()

    def _log_thread_uncaught(args) -> None:
        logging.getLogger("app.main").critical(
            "Eccezione non gestita nel thread %s",
            getattr(args.thread, "name", "?"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
        _flush_logs()

    def _log_unraisable(args) -> None:
        logging.getLogger("app.main").critical(
            "Eccezione non recuperabile: %s",
            getattr(args, "err_msg", "") or "",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
        _flush_logs()

    sys.excepthook = _log_uncaught
    threading.excepthook = _log_thread_uncaught
    sys.unraisablehook = _log_unraisable


def main() -> int:
    setup_logging()
    _install_crash_diagnostics()
    logger = logging.getLogger("app.main")
    logger.info("%s v%s avviato", APP_DISPLAY_NAME, __version__)

    # local-provider runtime pack (downloaded from Settings): if present, put
    # it on sys.path so the optional heavy imports work in the frozen app too
    try:
        from app.local_runtime import activate as activate_local_runtime

        activate_local_runtime()
    except Exception:
        logger.exception("Attivazione runtime locale fallita")

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

    # log the display layout: overlay placement and window/dialog positioning
    # depend on it, and past native crashes traced to a stale QScreen
    try:
        from PySide6.QtGui import QGuiApplication

        layout = ", ".join(
            f"{s.name()} {s.geometry().width()}x{s.geometry().height()}"
            for s in QGuiApplication.screens()
        )
        logger.info("Schermi rilevati: %s", layout or "(nessuno)")
    except Exception:
        logger.warning("Impossibile elencare gli schermi")

    # Real audio (M3), vMix (M4) and OpenAI provider (M7); without a saved key
    # the provider falls back to the fake demo
    secret_store = KeyringSecretStore()
    # SystemAudioInput = microphones/line-in (sounddevice) + system output capture
    # (WASAPI loopback via the optional 'soundcard' library, if installed)
    services = LiveAppServices(SystemAudioInput(), secret_store)

    if first_run:
        wizard = FirstRunWizard(
            config, services.list_audio_devices(), services, secret_store
        )
        if wizard.exec() == QDialog.DialogCode.Accepted:
            config = wizard.result_config()
            set_locale(config.ui_language)  # apply the chosen interface language
            try:
                manager.save(config)
            except OSError:
                logger.exception("Salvataggio configurazione fallito")
                QMessageBox.warning(
                    None,
                    APP_DISPLAY_NAME,
                    t("app.config_save_failed"),
                )
            # credentials were saved to secure storage by the wizard as the
            # operator advanced through the pages
        # wizard cancelled: nothing saved, so it reappears on the next launch

    window = MainWindow(manager, config, services, secret_store)
    window.show()

    if manager.load_warning:
        QMessageBox.warning(window, APP_DISPLAY_NAME, manager.load_warning)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
