# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""Application entry point: config + logging bootstrap, then the PySide6 GUI.

Milestone 2: the buttons are wired to MockAppServices (no real calls to
audio, provider or vMix).
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import TextIO

from app import APP_DISPLAY_NAME, APP_NAME, __version__
from app.audio.input import SystemAudioInput
from app.config.manager import ConfigManager
from app.config.models import describe_config
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


def _crash_log_mark(crash_file: TextIO | None, text: str) -> None:
    """Append a timestamped marker line to crash.log (best effort)."""
    if crash_file is None:
        return
    try:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        crash_file.write(f"--- {stamp} {text} ---\n")
        crash_file.flush()
    except Exception:
        pass


def _install_crash_diagnostics() -> TextIO | None:
    """Capture the Python stack of native crashes and uncaught exceptions.

    PySide6 6.x can abort the process on a native fault or an unhandled slot
    exception with no console (pythonw). faulthandler writes the faulting stack
    of every thread to crash.log, and the excepthook logs uncaught exceptions,
    so a crash leaves a readable trace instead of vanishing.

    Every run writes a start marker and, on a clean exit, an end marker: a
    dump (which carries no timestamp) is then attributable to its run, and a
    run with neither a dump nor an end marker was killed from outside (e.g.
    closed from Task Manager). Returns the open crash.log, or None.
    """
    import faulthandler

    from app.config.manager import get_log_dir

    crash_file = None
    try:
        log_dir = get_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        # kept open for the whole process lifetime (faulthandler writes on fault)
        crash_file = open(log_dir / "crash.log", "a", encoding="utf-8")  # noqa: SIM115
        _crash_log_mark(
            crash_file, f"avvio {APP_DISPLAY_NAME} v{__version__} (pid {os.getpid()})"
        )
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
    return crash_file


def main() -> int:
    setup_logging()
    crash_file = _install_crash_diagnostics()
    logger = logging.getLogger("app.main")
    logger.info("%s v%s avviato", APP_DISPLAY_NAME, __version__)

    manager = ConfigManager()
    first_run = not manager.config_path.exists()
    config = manager.load()
    # the full (secret-free) configuration: after a live show it tells exactly
    # how the program was set up
    logger.info("Configurazione: %s", describe_config(config))
    # activate the interface language before building any UI
    set_locale(config.ui_language)

    # local-provider runtime pack (downloaded from Settings): if present, put it
    # on sys.path (and register the CUDA DLL dirs for the GPU pack) so the
    # optional heavy imports work in the frozen app too. Use the configured
    # device, falling back to the CPU pack if only that one is installed.
    # Only when the local providers are offered or in use: hidden, there is no
    # reason to put torch & co. on sys.path of an OpenAI-only setup.
    try:
        from app.providers.registry import get_provider_info, local_providers_visible

        provider_info = get_provider_info(config.provider)
        if local_providers_visible() or (provider_info is not None and provider_info.local):
            from app.local_runtime import activate as activate_local_runtime

            if not activate_local_runtime(device=config.local_device):
                activate_local_runtime(device="cpu")
    except Exception:
        logger.exception("Attivazione runtime locale fallita")

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
        from app.gui.subtitle_overlay import describe_screens

        logger.info("Schermi rilevati: %s", describe_screens())
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

    exit_code = app.exec()
    logger.info("%s chiuso regolarmente (codice %s)", APP_DISPLAY_NAME, exit_code)
    _crash_log_mark(crash_file, "chiusura regolare")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
