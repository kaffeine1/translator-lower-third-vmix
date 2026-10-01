# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""Main window.

Audio/API/vMix status lights, subtitle preview, START/STOP and test buttons.
Orchestrates the pipeline through AppServices but contains no business logic:
provider, audio and vMix stay in their respective modules.
"""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app import (
    APP_DESCRIPTION,
    APP_DISPLAY_NAME,
    __author__,
    __author_email__,
    __version__,
)
from app.config.manager import ConfigManager, get_log_dir
from app.config.models import AppConfig, config_changes
from app.config.secrets import SecretStorageError, SecretStore
from app.gui.settings_dialog import SettingsDialog
from app.gui.subtitle_overlay import (
    SubtitleOverlay,
    describe_screen,
    describe_screens,
    screen_by_name,
)
from app.gui.widgets import AudioLevelMeter, StatusLight, StatusState, SubtitlePreview
from app.i18n import t
from app.services import STATUS_API, STATUS_VMIX, AppServices, ServiceResult

logger = logging.getLogger("app.gui")


AUDIO_TEST_DURATION_MS = 5000
AUDIO_DETECTED_THRESHOLD = 0.02
# on close, how long to wait for a START/STOP/test still running on a worker
# thread (a START can wait up to 10 s for the provider to answer)
SERVICE_JOIN_TIMEOUT_S = 15.0


class MainWindow(QMainWindow):
    # Real providers emit text from worker threads: the listener emits this
    # signal, and Qt delivers it on the GUI thread.
    subtitle_received = Signal(str)
    # Same for audio levels, which arrive from the PortAudio thread.
    audio_level = Signal(float)
    # Pipeline errors during translation (worker thread).
    translation_error = Signal(str)
    # Provider/vMix health during translation (worker thread):
    # (channel, ok, operator message or "").
    link_status = Signal(str, bool, str)
    # Results of service calls run on worker threads (HTTP etc.):
    # (result, completion callback to run on the GUI thread).
    _service_done = Signal(object, object)

    def __init__(
        self,
        config_manager: ConfigManager,
        config: AppConfig,
        services: AppServices,
        secret_store: SecretStore,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._manager = config_manager
        self._config = config
        self._services = services
        self._secret_store = secret_store

        self._audio_monitoring = False
        self._audio_peak = 0.0
        self._closing = False
        # START/STOP run on a worker thread: _run_busy while one is in flight,
        # _running while a translation is active
        self._run_busy = False
        self._running = False
        self._service_threads: set[threading.Thread] = set()
        self._audio_test_timer = QTimer(self)
        self._audio_test_timer.setSingleShot(True)
        self._audio_test_timer.setInterval(AUDIO_TEST_DURATION_MS)

        self._overlay: SubtitleOverlay | None = None

        self.setWindowTitle(APP_DISPLAY_NAME)
        self._build_ui()
        self._wire()
        self._setup_overlay()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)

        status_grid = QGridLayout()
        self.audio_light = StatusLight()
        self.api_light = StatusLight()
        self.vmix_light = StatusLight()
        for row, (label, light) in enumerate(
            [
                (t("gui.status_audio"), self.audio_light),
                (t("gui.status_api"), self.api_light),
                (t("gui.status_vmix"), self.vmix_light),
            ]
        ):
            status_grid.addWidget(QLabel(label), row, 0)
            status_grid.addWidget(light, row, 1)
        status_grid.setColumnStretch(2, 1)
        layout.addLayout(status_grid)

        layout.addWidget(QLabel(t("gui.preview_label")))
        self.preview = SubtitlePreview()
        layout.addWidget(self.preview)

        self.level_meter = AudioLevelMeter()
        layout.addWidget(self.level_meter)

        run_row = QHBoxLayout()
        self.btn_start = QPushButton("START")
        self.btn_start.setObjectName("btn_start")
        self.btn_start.setMinimumHeight(44)
        self.btn_stop = QPushButton("STOP")
        self.btn_stop.setObjectName("btn_stop")
        self.btn_stop.setMinimumHeight(44)
        self.btn_stop.setEnabled(False)
        run_row.addWidget(self.btn_start)
        run_row.addWidget(self.btn_stop)
        layout.addLayout(run_row)

        test_row = QHBoxLayout()
        self.btn_test_audio = QPushButton(t("gui.btn_test_audio"))
        self.btn_test_audio.setObjectName("btn_test_audio")
        self.btn_test_api = QPushButton(t("gui.btn_test_api"))
        self.btn_test_api.setObjectName("btn_test_api")
        self.btn_test_vmix = QPushButton(t("gui.btn_test_vmix"))
        self.btn_test_vmix.setObjectName("btn_test_vmix")
        for button in (self.btn_test_audio, self.btn_test_api, self.btn_test_vmix):
            test_row.addWidget(button)
        layout.addLayout(test_row)

        tools_row = QHBoxLayout()
        self.btn_settings = QPushButton(t("gui.btn_settings"))
        self.btn_settings.setObjectName("btn_settings")
        self.btn_open_log = QPushButton(t("gui.btn_open_log"))
        self.btn_open_log.setObjectName("btn_open_log")
        self.btn_info = QPushButton(t("gui.btn_info"))
        self.btn_info.setObjectName("btn_info")
        tools_row.addWidget(self.btn_settings)
        tools_row.addWidget(self.btn_open_log)
        tools_row.addWidget(self.btn_info)
        layout.addLayout(tools_row)

        # on-screen subtitle overlay: a checkable toggle for quick show/hide
        self.btn_overlay = QPushButton(t("gui.btn_overlay"))
        self.btn_overlay.setObjectName("btn_overlay")
        self.btn_overlay.setCheckable(True)
        layout.addWidget(self.btn_overlay)

        self.setCentralWidget(central)
        self.statusBar().showMessage(t("gui.status_ready"))

    def _wire(self) -> None:
        self.btn_start.clicked.connect(self._on_start)
        self.btn_stop.clicked.connect(self._on_stop)
        self.btn_test_audio.clicked.connect(self._on_test_audio)
        self.btn_test_api.clicked.connect(self._on_test_api)
        self.btn_test_vmix.clicked.connect(self._on_test_vmix)
        self.btn_settings.clicked.connect(self._on_settings)
        self.btn_open_log.clicked.connect(self._on_open_log)
        self.btn_info.clicked.connect(self._on_info)
        self.subtitle_received.connect(self.preview.set_text)
        self._services.set_subtitle_listener(self.subtitle_received.emit)
        self.translation_error.connect(self._on_translation_error)
        self._services.set_error_listener(self.translation_error.emit)
        self.link_status.connect(self._on_link_status)
        self._services.set_status_listener(self.link_status.emit)
        self.audio_level.connect(self._on_audio_level)
        self._audio_test_timer.timeout.connect(self._finish_audio_test)
        self._service_done.connect(self._on_service_done)
        self.btn_overlay.toggled.connect(self._on_overlay_toggled)
        self._services.update_config(self._config)

    # ------------------------------------------------------------------ slot

    # START and STOP run on a worker thread: connecting to the provider can
    # take up to 10 s and stopping waits for the workers and for vMix, and a
    # window frozen that long reads "Not responding" to the operator (clicks
    # made meanwhile would also fire late, all at once).

    def _on_start(self) -> None:
        if self._run_busy or self._running:
            return
        if self._audio_monitoring:
            self._finish_audio_test()
        self._run_busy = True
        self._update_run_buttons()
        self.statusBar().showMessage(t("gui.translation_starting"))
        self._call_service_async(self._services.start_translation, self._after_start)

    def _after_start(self, result: ServiceResult | None) -> None:
        self._run_busy = False
        self._running = bool(result and result.ok)
        self._update_run_buttons()

    def _on_stop(self) -> None:
        if self._run_busy or not self._running:
            return
        self._run_busy = True
        self._update_run_buttons()
        self.statusBar().showMessage(t("gui.translation_stopping"))
        self._call_service_async(self._services.stop_translation, self._after_stop)

    def _after_stop(self, result: ServiceResult | None) -> None:
        self._run_busy = False
        # a STOP that failed half-way keeps STOP available for another try
        self._running = bool(getattr(self._services, "running", False))
        self._update_run_buttons()

    def _update_run_buttons(self) -> None:
        busy, running = self._run_busy, self._running
        self.btn_start.setEnabled(not busy and not running)
        self.btn_stop.setEnabled(not busy and running)
        # the audio test would take over the capture device of the translation
        self.btn_test_audio.setEnabled(not busy and not running)
        self.btn_settings.setEnabled(not busy)

    def _on_translation_error(self, message: str) -> None:
        # live error: visible but not modal (does not interrupt the event); the
        # status lights follow link_status, which knows whether the provider or
        # vMix is failing
        self.statusBar().showMessage(message, 8000)
        logger.warning("Errore traduzione: %s", message)

    def _on_link_status(self, channel: str, ok: bool, message: str) -> None:
        light = {STATUS_API: self.api_light, STATUS_VMIX: self.vmix_light}.get(channel)
        if light is not None:
            light.set_state(StatusState.GREEN if ok else StatusState.RED)
        if message:
            self.statusBar().showMessage(message, 8000)
            (logger.info if ok else logger.warning)("%s", message)

    def _on_test_audio(self) -> None:
        if self._audio_monitoring:
            self._finish_audio_test()
            return
        device_id = self._config.audio.device_id
        # peak and flag must be set BEFORE start: levels can already
        # arrive during the call (the mock emits them synchronously)
        self._audio_peak = 0.0
        self._audio_monitoring = True
        result = self._call_service(
            lambda: self._services.start_audio_monitor(device_id, self.audio_level.emit)
        )
        if not result or not result.ok:
            self._audio_monitoring = False
            self.audio_light.set_state(StatusState.RED)
            return
        self.btn_test_audio.setText(t("gui.btn_stop_test"))
        self._audio_test_timer.start()

    def _on_audio_level(self, level: float) -> None:
        # levels arrive queued from the audio thread: those still in flight
        # when the test ends must not light the meter back up
        if not self._audio_monitoring:
            return
        self.level_meter.set_level(level)
        self._audio_peak = max(self._audio_peak, level)

    def _finish_audio_test(self) -> None:
        if not self._audio_monitoring:
            return
        self._audio_monitoring = False
        self._audio_test_timer.stop()
        try:
            self._services.stop_audio_monitor()
        except Exception:
            logger.exception("Errore fermando il test audio")
        self.btn_test_audio.setText(t("gui.btn_test_audio"))
        self.level_meter.set_level(0.0)
        detected = self._audio_peak > AUDIO_DETECTED_THRESHOLD
        self.audio_light.set_state(StatusState.GREEN if detected else StatusState.RED)
        message = t("gui.audio_detected") if detected else t("gui.audio_none")
        self.statusBar().showMessage(message, 5000)
        (logger.info if detected else logger.warning)("%s", message)

    def _on_test_api(self) -> None:
        self.btn_test_api.setEnabled(False)
        self._call_service_async(self._services.test_api, self._after_test_api)

    def _after_test_api(self, result: ServiceResult | None) -> None:
        self.btn_test_api.setEnabled(True)
        ok = bool(result and result.ok)
        self.api_light.set_state(StatusState.GREEN if ok else StatusState.RED)

    def _on_test_vmix(self) -> None:
        self.btn_test_vmix.setEnabled(False)
        self.statusBar().showMessage(t("gui.vmix_checking"))
        self._call_service_async(self._services.test_vmix, self._after_test_vmix)

    def _after_test_vmix(self, result: ServiceResult | None) -> None:
        self.btn_test_vmix.setEnabled(True)
        ok = bool(result and result.ok)
        self.vmix_light.set_state(StatusState.GREEN if ok else StatusState.RED)

    def _on_settings(self) -> None:
        dialog = SettingsDialog(
            self._config,
            self._services.list_audio_devices(),
            saved_accounts=self._saved_accounts(),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._apply_settings(dialog.result_config(), dialog.entered_credentials())

    def _apply_settings(self, new_config: AppConfig, credentials: dict[str, str]) -> bool:
        """Persists config and any entered credentials, showing errors clearly."""
        old_config = self._config
        try:
            self._manager.save(new_config)
        except OSError:
            logger.exception("Salvataggio configurazione fallito")
            QMessageBox.critical(
                self,
                t("gui.settings_title"),
                t("gui.settings_save_failed"),
            )
            return False
        changes = config_changes(old_config, new_config) if old_config is not None else []
        if changes:
            logger.info("Impostazioni modificate: %s", "; ".join(changes))
        self._config = new_config
        self._services.update_config(new_config)
        # invalidate ONLY the status lights whose settings actually changed, so
        # editing subtitles/overlay does not wipe a green Audio/API/vMix result
        if old_config is None or old_config.audio.device_id != new_config.audio.device_id:
            self.audio_light.set_state(StatusState.YELLOW)
        if old_config is None or old_config.provider != new_config.provider or credentials:
            self.api_light.set_state(StatusState.YELLOW)
        if old_config is None or old_config.vmix != new_config.vmix:
            self.vmix_light.set_state(StatusState.YELLOW)
        for account, value in credentials.items():
            try:
                self._secret_store.set_api_key(account, value)
            except SecretStorageError as exc:
                QMessageBox.warning(self, t("gui.settings_title"), str(exc))
                return False
        # overlay settings may have changed (monitor/font/opacity/enabled)
        self._sync_overlay_button()
        self._apply_overlay_state()
        # the local CPU/GPU pack is chosen at startup (before faster-whisper is
        # imported), so switching device only takes effect after a restart —
        # tell the operator instead of silently keeping the old device
        if old_config is not None and old_config.local_device != new_config.local_device:
            QMessageBox.information(
                self,
                t("gui.settings_title"),
                t("gui.local_device_restart"),
            )
        vmix_changes = self._describe_vmix_changes(old_config, new_config)
        if vmix_changes:
            # a vMix address/title changed without the operator noticing (the
            # mouse wheel over the port field) is what silently broke a live
            # show: spell out the change and point to Test vMix
            self.statusBar().showMessage(
                t("gui.settings_saved_vmix_changed", changes=vmix_changes), 20000
            )
        else:
            self.statusBar().showMessage(t("gui.settings_saved"), 5000)
        return True

    @staticmethod
    def _describe_vmix_changes(old: AppConfig | None, new: AppConfig) -> str:
        """The changed vMix settings as "Porta 8088 → 8087" (empty if none)."""
        if old is None:
            return ""
        fields = (
            ("host", "settings.label.vmix_host"),
            ("port", "settings.label.vmix_port"),
            ("input", "settings.label.vmix_input"),
            ("selected_name", "settings.label.vmix_field"),
        )
        parts = []
        for attr, label_key in fields:
            before, after = getattr(old.vmix, attr), getattr(new.vmix, attr)
            if before != after:
                shown = [str(v) if str(v) else t("gui.value_empty") for v in (before, after)]
                parts.append(f"{t(label_key).rstrip(':')} {shown[0]} → {shown[1]}")
        return ", ".join(parts)

    # ------------------------------------------------------------------ overlay

    def _setup_overlay(self) -> None:
        # Parentless top-level: an independent caption surface on any monitor,
        # deliberately NOT a child of the main window. As a child, the main
        # window's activation/screen churn (e.g. showing a dialog, moving
        # between monitors) drove Qt to reposition the translucent tool window
        # and query a screen that could already be gone — a native crash in
        # QScreen::geometry(). A parentless window is decoupled from that.
        self._overlay = SubtitleOverlay()
        # feed it the same published subtitle text as the preview
        self.subtitle_received.connect(self._overlay.set_text)
        # re-place (or hide) the overlay when the display layout changes, so it
        # never keeps a native window on a screen that has been removed
        gui_app = QGuiApplication.instance()
        if gui_app is not None:
            gui_app.screenAdded.connect(self._on_screen_added)
            gui_app.screenRemoved.connect(self._on_screen_removed)
            gui_app.primaryScreenChanged.connect(self._on_primary_screen_changed)
        self._sync_overlay_button()
        self._apply_overlay_state()
        if self._config.overlay.enabled:
            logger.info(
                "Sottotitoli a schermo attivi all'avvio (monitor: %s)",
                self._overlay_monitor_label(),
            )

    # display-layout changes are logged: a monitor or extender dropping out
    # during a show is otherwise invisible in a post-mortem

    def _on_screen_added(self, screen) -> None:
        logger.info("Schermo collegato: %s", describe_screen(screen))
        self._on_screens_changed()

    def _on_screen_removed(self, screen) -> None:
        logger.warning("Schermo scollegato: %s", describe_screen(screen))
        self._on_screens_changed()

    def _on_primary_screen_changed(self, screen) -> None:
        logger.info("Schermo principale cambiato: %s", describe_screen(screen))
        self._on_screens_changed()

    def _on_screens_changed(self, *_args) -> None:
        """React to a display-layout change (monitor added/removed/primary
        swapped): detach the overlay from any now-invalid screen and re-place it
        on a valid one, so a stale QScreen is never dereferenced."""
        if self._closing or self._overlay is None:
            return
        try:
            logger.info("Schermi collegati ora: %s", describe_screens())
            self._overlay.hide()  # drop the native window off a possibly-dead screen
            self._apply_overlay_state()
        except Exception:
            logger.exception("Errore riposizionando l'overlay dopo un cambio schermo")

    def _apply_overlay_state(self) -> None:
        """Apply style + monitor and show/hide the overlay from the config."""
        if self._overlay is None:
            return
        overlay_cfg = self._config.overlay
        try:
            self._overlay.apply_config(
                font_point_size=overlay_cfg.font_point_size,
                background_opacity=overlay_cfg.background_opacity,
            )
            if overlay_cfg.enabled:
                screen = screen_by_name(overlay_cfg.monitor)
                if overlay_cfg.monitor and (screen is None or screen.name() != overlay_cfg.monitor):
                    logger.warning(
                        "Monitor '%s' dei sottotitoli non collegato: uso %s",
                        overlay_cfg.monitor,
                        describe_screen(screen),
                    )
                self._overlay.show_on(screen)
            else:
                self._overlay.hide()
        except Exception:
            logger.exception("Errore applicando l'overlay sottotitoli")

    def _sync_overlay_button(self) -> None:
        # reflect config on the toggle without re-triggering the toggled slot
        self.btn_overlay.blockSignals(True)
        self.btn_overlay.setChecked(self._config.overlay.enabled)
        self.btn_overlay.blockSignals(False)

    def _overlay_monitor_label(self) -> str:
        return self._config.overlay.monitor or "principale"

    def _on_overlay_toggled(self, checked: bool) -> None:
        self._config.overlay.enabled = checked
        logger.info(
            "Sottotitoli a schermo %s dal pulsante (monitor: %s)",
            "attivati" if checked else "disattivati",
            self._overlay_monitor_label(),
        )
        try:
            self._manager.save(self._config)
        except OSError:
            logger.exception("Salvataggio stato overlay fallito")
        self._apply_overlay_state()

    def closeEvent(self, event) -> None:  # noqa: N802 (name imposed by Qt)
        logger.info("Finestra principale chiusa")
        self._closing = True
        if self._overlay is not None:
            self._overlay.close()
        if self._audio_monitoring:
            self._finish_audio_test()
        # wait for service calls still running on worker threads (their own
        # timeouts bound the wait): a START completing after the window is
        # gone must not leave a translation running with nobody to stop it,
        # and no signal may be emitted during interpreter teardown
        for thread in list(self._service_threads):
            thread.join(timeout=SERVICE_JOIN_TIMEOUT_S)
        # translation running: stop it to avoid leaving dangling threads
        if getattr(self._services, "running", False):
            try:
                self._services.stop_translation()
            except Exception:
                logger.exception("Errore fermando la traduzione alla chiusura")
        super().closeEvent(event)

    def _on_open_log(self) -> None:
        log_dir = get_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir)))

    def diagnostics_text(self) -> str:
        """Text of the Info/About screen: author, version, paths.

        Never contains secrets (the API key is only reported as present)."""
        provider = self._config.provider
        has_key = self._has_saved_api_key()
        from app.providers.registry import get_provider_info

        info = get_provider_info(provider)
        # a provider that detects the spoken language ignores the saved one
        source_language = (
            t("gui.source_auto_short")
            if info is not None and info.detects_source_language
            else self._config.source_language
        )
        return t(
            "gui.diagnostics",
            app_name=APP_DISPLAY_NAME,
            version=__version__,
            description=APP_DESCRIPTION,
            author=__author__,
            author_email=__author_email__,
            provider=provider,
            has_key=t("gui.yes") if has_key else t("gui.no"),
            source_language=source_language,
            target_language=self._config.target_language,
            vmix_host=self._config.vmix.host,
            vmix_port=self._config.vmix.port,
            config_path=self._manager.config_path,
            log_dir=get_log_dir(),
        )

    def _on_info(self) -> None:
        QMessageBox.about(
            self, t("gui.info_title", app_name=APP_DISPLAY_NAME), self.diagnostics_text()
        )

    # ------------------------------------------------------------------ helper

    def _call_service(self, operation) -> ServiceResult | None:
        """Runs a service operation, showing the outcome to the operator."""
        try:
            result = operation()
        except Exception:
            logger.exception("Errore inatteso in %s", getattr(operation, "__name__", "servizio"))
            QMessageBox.critical(
                self,
                APP_DISPLAY_NAME,
                t("gui.unexpected_error"),
            )
            return None
        self.statusBar().showMessage(result.message, 5000)
        (logger.info if result.ok else logger.warning)("%s", result.message)
        return result

    def _call_service_async(self, operation, on_done) -> None:
        """Like _call_service but on a worker thread: HTTP calls must never
        freeze the GUI. on_done(result|None) arrives on the Qt thread."""

        def runner() -> None:
            try:
                result = operation()
            except Exception:
                logger.exception(
                    "Errore inatteso in %s", getattr(operation, "__name__", "servizio")
                )
                result = None
            # after closeEvent we no longer emit: the signal would arrive
            # during Qt/interpreter teardown
            if not self._closing:
                self._service_done.emit(result, on_done)

        self._service_threads = {t for t in self._service_threads if t.is_alive()}
        thread = threading.Thread(target=runner, daemon=True, name="service-call")
        self._service_threads.add(thread)
        thread.start()

    def _on_service_done(self, result: ServiceResult | None, on_done) -> None:
        if result is None:
            self.statusBar().showMessage(t("gui.operation_failed"), 5000)
            QMessageBox.critical(
                self,
                APP_DISPLAY_NAME,
                t("gui.unexpected_error"),
            )
        else:
            self.statusBar().showMessage(result.message, 5000)
            (logger.info if result.ok else logger.warning)("%s", result.message)
        on_done(result)

    def _has_saved_api_key(self) -> bool:
        """True if every credential the current provider needs is stored."""
        from app.providers.registry import get_provider_info

        info = get_provider_info(self._config.provider)
        names = info.required_key_names if info else ()
        return bool(names) and all(self._has_account(name) for name in names)

    def _has_account(self, account: str) -> bool:
        try:
            return bool(self._secret_store.get_api_key(account))
        except SecretStorageError:
            return False

    def _saved_accounts(self) -> set[str]:
        """Secure-storage accounts that currently hold a value (for placeholders)."""
        from app.providers.registry import all_credential_accounts

        return {acc for acc in all_credential_accounts() if self._has_account(acc)}
