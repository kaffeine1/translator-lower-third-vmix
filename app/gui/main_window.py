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
from PySide6.QtGui import QDesktopServices
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
from app.config.models import AppConfig
from app.config.secrets import SecretStorageError, SecretStore
from app.gui.settings_dialog import SettingsDialog
from app.gui.widgets import AudioLevelMeter, StatusLight, StatusState, SubtitlePreview
from app.i18n import t
from app.services import AppServices, ServiceResult

logger = logging.getLogger("app.gui")


AUDIO_TEST_DURATION_MS = 5000
AUDIO_DETECTED_THRESHOLD = 0.02


class MainWindow(QMainWindow):
    # Real providers emit text from worker threads: the listener emits this
    # signal, and Qt delivers it on the GUI thread.
    subtitle_received = Signal(str)
    # Same for audio levels, which arrive from the PortAudio thread.
    audio_level = Signal(float)
    # Pipeline errors during translation (worker thread).
    translation_error = Signal(str)
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
        self._service_threads: set[threading.Thread] = set()
        self._audio_test_timer = QTimer(self)
        self._audio_test_timer.setSingleShot(True)
        self._audio_test_timer.setInterval(AUDIO_TEST_DURATION_MS)

        self.setWindowTitle(APP_DISPLAY_NAME)
        self._build_ui()
        self._wire()

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
        self.audio_level.connect(self._on_audio_level)
        self._audio_test_timer.timeout.connect(self._finish_audio_test)
        self._service_done.connect(self._on_service_done)
        self._services.update_config(self._config)

    # ------------------------------------------------------------------ slot

    def _on_start(self) -> None:
        if self._audio_monitoring:
            self._finish_audio_test()
        result = self._call_service(self._services.start_translation)
        if result and result.ok:
            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(True)

    def _on_stop(self) -> None:
        result = self._call_service(self._services.stop_translation)
        if result and result.ok:
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)

    def _on_translation_error(self, message: str) -> None:
        # live error: visible but not modal (does not interrupt the event)
        self.vmix_light.set_state(StatusState.RED)
        self.statusBar().showMessage(message, 8000)
        logger.warning("Errore traduzione: %s", message)

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
        self._config = new_config
        self._services.update_config(new_config)
        # config changed: previous test results are no longer valid
        for light in (self.audio_light, self.api_light, self.vmix_light):
            light.set_state(StatusState.YELLOW)
        for account, value in credentials.items():
            try:
                self._secret_store.set_api_key(account, value)
            except SecretStorageError as exc:
                QMessageBox.warning(self, t("gui.settings_title"), str(exc))
                return False
        self.statusBar().showMessage(t("gui.settings_saved"), 5000)
        return True

    def closeEvent(self, event) -> None:  # noqa: N802 (name imposed by Qt)
        self._closing = True
        if self._audio_monitoring:
            self._finish_audio_test()
        # translation running: stop it to avoid leaving dangling threads
        if self.btn_stop.isEnabled():
            try:
                self._services.stop_translation()
            except Exception:
                logger.exception("Errore fermando la traduzione alla chiusura")
        # brief wait for in-flight service threads: the httpx timeout (2 s
        # × 2 attempts) bounds the wait and avoids emitting signals
        # during interpreter teardown
        for thread in self._service_threads:
            thread.join(timeout=5.0)
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
        return t(
            "gui.diagnostics",
            app_name=APP_DISPLAY_NAME,
            version=__version__,
            description=APP_DESCRIPTION,
            author=__author__,
            author_email=__author_email__,
            provider=provider,
            has_key=t("gui.yes") if has_key else t("gui.no"),
            source_language=self._config.source_language,
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
