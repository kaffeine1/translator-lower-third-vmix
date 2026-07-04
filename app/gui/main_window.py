# Translator Lower Third for vMix
# Autore: Michele Dipace <michele.dipace@kaffeine.net>
"""Finestra principale.

Semafori Audio/API/vMix, anteprima sottotitolo, START/STOP e pulsanti di test.
Orchestra il pipeline tramite AppServices ma non contiene logica di business:
provider, audio e vMix restano nei rispettivi moduli.
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
from app.services import AppServices, ServiceResult

logger = logging.getLogger("app.gui")


AUDIO_TEST_DURATION_MS = 5000
AUDIO_DETECTED_THRESHOLD = 0.02


class MainWindow(QMainWindow):
    # I provider reali emettono testo da thread di lavoro: il listener emette
    # questo segnale, Qt lo consegna sul thread GUI.
    subtitle_received = Signal(str)
    # Idem per i livelli audio, che arrivano dal thread PortAudio.
    audio_level = Signal(float)
    # Errori del pipeline durante la traduzione (thread di lavoro).
    translation_error = Signal(str)
    # Esiti delle chiamate servizi eseguite su thread di lavoro (HTTP ecc.):
    # (risultato, callback di completamento da eseguire sul thread GUI).
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
                ("Stato Audio:", self.audio_light),
                ("Stato API:", self.api_light),
                ("Stato vMix:", self.vmix_light),
            ]
        ):
            status_grid.addWidget(QLabel(label), row, 0)
            status_grid.addWidget(light, row, 1)
        status_grid.setColumnStretch(2, 1)
        layout.addLayout(status_grid)

        layout.addWidget(QLabel("Anteprima sottotitolo:"))
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
        self.btn_test_audio = QPushButton("Test Audio")
        self.btn_test_audio.setObjectName("btn_test_audio")
        self.btn_test_api = QPushButton("Test API")
        self.btn_test_api.setObjectName("btn_test_api")
        self.btn_test_vmix = QPushButton("Test vMix")
        self.btn_test_vmix.setObjectName("btn_test_vmix")
        for button in (self.btn_test_audio, self.btn_test_api, self.btn_test_vmix):
            test_row.addWidget(button)
        layout.addLayout(test_row)

        tools_row = QHBoxLayout()
        self.btn_settings = QPushButton("Impostazioni")
        self.btn_settings.setObjectName("btn_settings")
        self.btn_open_log = QPushButton("Apri Log")
        self.btn_open_log.setObjectName("btn_open_log")
        self.btn_info = QPushButton("Info")
        self.btn_info.setObjectName("btn_info")
        tools_row.addWidget(self.btn_settings)
        tools_row.addWidget(self.btn_open_log)
        tools_row.addWidget(self.btn_info)
        layout.addLayout(tools_row)

        self.setCentralWidget(central)
        self.statusBar().showMessage("Pronto")

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
        # errore in diretta: visibile ma non modale (non interrompe l'evento)
        self.vmix_light.set_state(StatusState.RED)
        self.statusBar().showMessage(message, 8000)
        logger.warning("Errore traduzione: %s", message)

    def _on_test_audio(self) -> None:
        if self._audio_monitoring:
            self._finish_audio_test()
            return
        device_id = self._config.audio.device_id
        # picco e flag vanno impostati PRIMA dello start: i livelli possono
        # arrivare già durante la chiamata (il mock li emette in modo sincrono)
        self._audio_peak = 0.0
        self._audio_monitoring = True
        result = self._call_service(
            lambda: self._services.start_audio_monitor(device_id, self.audio_level.emit)
        )
        if not result or not result.ok:
            self._audio_monitoring = False
            self.audio_light.set_state(StatusState.RED)
            return
        self.btn_test_audio.setText("Ferma Test")
        self._audio_test_timer.start()

    def _on_audio_level(self, level: float) -> None:
        # i livelli arrivano in coda dal thread audio: quelli già in volo
        # quando il test finisce non devono riaccendere il meter
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
        self.btn_test_audio.setText("Test Audio")
        self.level_meter.set_level(0.0)
        detected = self._audio_peak > AUDIO_DETECTED_THRESHOLD
        self.audio_light.set_state(StatusState.GREEN if detected else StatusState.RED)
        message = "Audio rilevato" if detected else "Nessun audio in ingresso"
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
        self.statusBar().showMessage("Verifica vMix in corso…")
        self._call_service_async(self._services.test_vmix, self._after_test_vmix)

    def _after_test_vmix(self, result: ServiceResult | None) -> None:
        self.btn_test_vmix.setEnabled(True)
        ok = bool(result and result.ok)
        self.vmix_light.set_state(StatusState.GREEN if ok else StatusState.RED)

    def _on_settings(self) -> None:
        dialog = SettingsDialog(
            self._config,
            self._services.list_audio_devices(),
            has_saved_api_key=self._has_saved_api_key(),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._apply_settings(dialog.result_config(), dialog.entered_api_key())

    def _apply_settings(self, new_config: AppConfig, api_key: str) -> bool:
        """Persiste config e chiave API mostrando gli errori all'operatore."""
        try:
            self._manager.save(new_config)
        except OSError:
            logger.exception("Salvataggio configurazione fallito")
            QMessageBox.critical(
                self,
                "Impostazioni",
                "Impossibile salvare le impostazioni su disco. "
                "Controlla lo spazio disponibile e i permessi, poi riprova.",
            )
            return False
        self._config = new_config
        self._services.update_config(new_config)
        # config cambiata: gli esiti dei test precedenti non valgono più
        for light in (self.audio_light, self.api_light, self.vmix_light):
            light.set_state(StatusState.YELLOW)
        if api_key:
            try:
                self._secret_store.set_api_key(new_config.provider, api_key)
            except SecretStorageError as exc:
                QMessageBox.warning(self, "Impostazioni", str(exc))
                return False
        self.statusBar().showMessage("Impostazioni salvate", 5000)
        return True

    def closeEvent(self, event) -> None:  # noqa: N802 (nome imposto da Qt)
        self._closing = True
        if self._audio_monitoring:
            self._finish_audio_test()
        # traduzione in corso: fermala per non lasciare thread appesi
        if self.btn_stop.isEnabled():
            try:
                self._services.stop_translation()
            except Exception:
                logger.exception("Errore fermando la traduzione alla chiusura")
        # attesa breve dei thread di servizio in volo: il timeout httpx (2 s
        # × 2 tentativi) limita l'attesa e si evita di emettere segnali
        # durante lo smontaggio dell'interprete
        for thread in self._service_threads:
            thread.join(timeout=5.0)
        super().closeEvent(event)

    def _on_open_log(self) -> None:
        log_dir = get_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir)))

    def diagnostics_text(self) -> str:
        """Testo della schermata Info/About: autore, versione, percorsi.

        Non contiene mai segreti (la chiave API è indicata solo come presente)."""
        provider = self._config.provider
        has_key = self._has_saved_api_key()
        return (
            f"{APP_DISPLAY_NAME}\n"
            f"Versione: {__version__}\n"
            f"{APP_DESCRIPTION}\n\n"
            f"Autore: {__author__} <{__author_email__}>\n\n"
            f"Provider: {provider}\n"
            f"Chiave API salvata: {'sì' if has_key else 'no'}\n"
            f"Lingue: {self._config.source_language} → {self._config.target_language}\n"
            f"vMix: {self._config.vmix.host}:{self._config.vmix.port}\n\n"
            f"Configurazione:\n{self._manager.config_path}\n\n"
            f"Log:\n{get_log_dir()}"
        )

    def _on_info(self) -> None:
        QMessageBox.about(self, f"Informazioni su {APP_DISPLAY_NAME}", self.diagnostics_text())

    # ------------------------------------------------------------------ helper

    def _call_service(self, operation) -> ServiceResult | None:
        """Esegue un'operazione dei servizi mostrando l'esito all'operatore."""
        try:
            result = operation()
        except Exception:
            logger.exception("Errore inatteso in %s", getattr(operation, "__name__", "servizio"))
            QMessageBox.critical(
                self,
                APP_DISPLAY_NAME,
                "Si è verificato un errore inatteso. Consulta i log (pulsante Apri Log).",
            )
            return None
        self.statusBar().showMessage(result.message, 5000)
        (logger.info if result.ok else logger.warning)("%s", result.message)
        return result

    def _call_service_async(self, operation, on_done) -> None:
        """Come _call_service ma su thread di lavoro: le chiamate HTTP non
        devono mai congelare la GUI. on_done(result|None) arriva sul thread Qt."""

        def runner() -> None:
            try:
                result = operation()
            except Exception:
                logger.exception(
                    "Errore inatteso in %s", getattr(operation, "__name__", "servizio")
                )
                result = None
            # dopo closeEvent non si emette più: il segnale arriverebbe
            # durante lo smontaggio di Qt/interprete
            if not self._closing:
                self._service_done.emit(result, on_done)

        self._service_threads = {t for t in self._service_threads if t.is_alive()}
        thread = threading.Thread(target=runner, daemon=True, name="service-call")
        self._service_threads.add(thread)
        thread.start()

    def _on_service_done(self, result: ServiceResult | None, on_done) -> None:
        if result is None:
            self.statusBar().showMessage("Operazione non riuscita", 5000)
            QMessageBox.critical(
                self,
                APP_DISPLAY_NAME,
                "Si è verificato un errore inatteso. Consulta i log (pulsante Apri Log).",
            )
        else:
            self.statusBar().showMessage(result.message, 5000)
            (logger.info if result.ok else logger.warning)("%s", result.message)
        on_done(result)

    def _has_saved_api_key(self) -> bool:
        try:
            return self._secret_store.get_api_key(self._config.provider) is not None
        except SecretStorageError:
            return False
