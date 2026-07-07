# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""First-run wizard.

Steps: language & provider → provider credentials → provider test → audio input
→ vMix → vMix test → save and start.

Provider-aware: the credentials page shows the fields required by the selected
provider (from the registry credential descriptors) and saves them to secure
storage when advancing, so the provider/vMix tests run against real values. The
caller persists the (non-sensitive) config via result_config(); the credentials
are saved by the wizard itself. The tests (provider/vMix) run on worker threads:
HTTP calls must never freeze the wizard.
"""

from __future__ import annotations

import importlib.util
import logging
import threading

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from app import local_runtime
from app.audio.devices import AudioDevice
from app.config.models import LOCAL_DEVICES, LOCAL_MODELS, AppConfig
from app.config.secrets import SecretStorageError, SecretStore
from app.gui.settings_dialog import LANGUAGES, SYSTEM_DEFAULT_DEVICE, _select_by_data
from app.i18n import available_locales, t
from app.providers.registry import available_providers, get_provider_info
from app.services import AppServices

logger = logging.getLogger("app.gui")


class _CredentialsPage(QWizardPage):
    """Shows one field per credential the selected provider needs and saves them
    to secure storage when advancing (so the following tests can use them). For
    the local provider it offers the component/model download instead — the same
    inline pattern as the Settings dialog (signals and slots on the host: a
    child widget class carrying its own signals proved fragile at teardown)."""

    # worker-thread -> GUI marshalling for the local-runtime downloads
    _runtime_progress = Signal(int, int)  # done bytes, total bytes (0 = unknown)
    _worker_status = Signal(str)
    _worker_done = Signal(bool, str)  # ok, operator message

    def __init__(self, wizard: FirstRunWizard) -> None:
        super().__init__()
        self._wizard = wizard
        self.setTitle(t("wizard.credentials.title"))
        layout = QVBoxLayout(self)
        hint = QLabel(t("wizard.credentials.hint"))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self._form = QFormLayout()
        layout.addLayout(self._form)
        self._edits: dict[str, QLineEdit] = {}
        # local provider: no credentials, but the heavy components/models may
        # need downloading — same controls as in Settings, shown only for "local"
        self._local_hint = QLabel(t("wizard.credentials.local_hint"))
        self._local_hint.setWordWrap(True)
        layout.addWidget(self._local_hint)
        # speech-model + device choices drive what/which pack "download" fetches
        self._local_form = QFormLayout()
        self.local_model_combo = QComboBox()
        for size in LOCAL_MODELS:
            self.local_model_combo.addItem(size, size)
        _select_by_data(self.local_model_combo, wizard._base_config.local_model)
        self._local_model_label = QLabel(t("wizard.local.model_label"))
        self._local_form.addRow(self._local_model_label, self.local_model_combo)
        self.local_device_combo = QComboBox()
        for code in LOCAL_DEVICES:
            self.local_device_combo.addItem(t(f"settings.device.{code}"), code)
        _select_by_data(self.local_device_combo, wizard._base_config.local_device)
        self._local_device_label = QLabel(t("settings.label.local_device"))
        self._local_form.addRow(self._local_device_label, self.local_device_combo)
        layout.addLayout(self._local_form)
        self.runtime_status_label = QLabel()
        self.runtime_status_label.setWordWrap(True)
        layout.addWidget(self.runtime_status_label)
        self.btn_download_runtime = QPushButton()  # label set in _sync_runtime_button_label
        self.btn_download_runtime.setObjectName("btn_download_runtime")
        layout.addWidget(self.btn_download_runtime)
        self.btn_download_models = QPushButton(t("settings.btn_download_models"))
        self.btn_download_models.setObjectName("btn_download_models")
        layout.addWidget(self.btn_download_models)
        self.runtime_progress = QProgressBar()
        self.runtime_progress.setVisible(False)
        layout.addWidget(self.runtime_progress)
        layout.addStretch()
        self.btn_download_runtime.clicked.connect(self._on_download_runtime)
        self.btn_download_models.clicked.connect(self._on_download_models)
        self._runtime_progress.connect(self._on_runtime_progress)
        self._worker_status.connect(self.runtime_status_label.setText)
        self._worker_done.connect(self._on_worker_done)
        # a different speech model (or languages, from step 1) means a
        # different download: keep the status hint truthful
        self.local_model_combo.currentIndexChanged.connect(self._refresh_models_state)
        # CPU<->GPU switches to a different pack (and its size)
        self.local_device_combo.currentIndexChanged.connect(self._on_device_changed)
        self._sync_runtime_button_label()

    def initializePage(self) -> None:  # noqa: N802 (Qt name)
        while self._form.rowCount():
            self._form.removeRow(0)
        self._edits.clear()
        provider_id = self._wizard.provider_combo.currentData()
        is_local = provider_id == "local"
        self._local_hint.setVisible(is_local)
        self._local_model_label.setVisible(is_local)
        self.local_model_combo.setVisible(is_local)
        self._local_device_label.setVisible(is_local)
        self.local_device_combo.setVisible(is_local)
        self.runtime_status_label.setVisible(is_local)
        self.btn_download_models.setVisible(is_local)
        self.runtime_progress.setVisible(False)
        if is_local:
            self._refresh_runtime_state()
        else:
            self.btn_download_runtime.setVisible(False)
        info = get_provider_info(provider_id)
        credentials = info.credentials if info else ()
        if not credentials:
            if not is_local:  # for "local" the download controls explain the setup
                self._form.addRow(QLabel(t("wizard.credentials.none")))
            return
        for cred in credentials:
            edit = QLineEdit()
            if cred.secret:
                edit.setEchoMode(QLineEdit.EchoMode.Password)
            self._form.addRow(t(cred.label_key), edit)
            self._edits[cred.account] = edit

    # ---------------------------------------------------------- local runtime

    def _selected_device(self) -> str:
        return self.local_device_combo.currentData()

    def _local_components_available(self) -> bool:
        """True when the components for the SELECTED device are usable (see the
        Settings dialog for the same device-aware logic)."""
        device = self._selected_device()
        if local_runtime.is_installed(device=device):
            return True
        no_pack = not local_runtime.is_installed(device="cpu") and not local_runtime.is_installed(
            device="cuda"
        )
        if no_pack:
            return importlib.util.find_spec("faster_whisper") is not None
        return False

    def _sync_runtime_button_label(self) -> None:
        size_bytes = local_runtime.pack_for(self._selected_device()).size_bytes
        size_text = f"{size_bytes // 1_000_000} MB" if size_bytes else "1 GB"
        self.btn_download_runtime.setText(t("settings.btn_download_runtime", size=size_text))

    def _on_device_changed(self) -> None:
        self._sync_runtime_button_label()
        self._refresh_runtime_state()

    def _refresh_runtime_state(self) -> None:
        available = self._local_components_available()
        self.runtime_status_label.setText(
            t("settings.runtime_status_present")
            if available
            else t("settings.runtime_status_absent")
        )
        self.btn_download_runtime.setVisible(not available)
        self.btn_download_models.setEnabled(available)
        if available:
            self._refresh_models_state()

    def _refresh_models_state(self) -> None:
        """Reflect whether the models for the current selection are already
        downloaded (same behavior as the Settings dialog)."""
        if not self._local_components_available():
            return
        config = self._wizard.result_config()
        cached = local_runtime.models_cached(
            config.local_model, config.source_language, config.target_language
        )
        if cached is None:
            return
        if cached:
            self.runtime_status_label.setText(t("settings.models_state_present"))
        else:
            names = ", ".join(
                local_runtime.required_model_repos(
                    config.local_model, config.source_language, config.target_language
                )
            )
            self.runtime_status_label.setText(
                t("settings.models_state_missing", names=names)
            )

    def _on_download_runtime(self) -> None:
        self.btn_download_runtime.setEnabled(False)
        self.btn_download_models.setEnabled(False)
        self.runtime_progress.setVisible(True)
        self.runtime_progress.setRange(0, 0)  # busy until the size is known
        device = self._selected_device()

        def worker() -> None:
            try:
                local_runtime.download_and_install(
                    device=device,
                    progress=lambda done, total: self._runtime_progress.emit(done, total),
                )
            except local_runtime.LocalRuntimeError as exc:
                self._worker_done.emit(False, str(exc))
                return
            except Exception:
                logger.exception("Installazione runtime locale fallita")
                self._worker_done.emit(False, t("runtime.download_failed"))
                return
            self._worker_done.emit(True, t("settings.runtime_ready"))

        threading.Thread(target=worker, daemon=True, name="runtime-download").start()

    def _on_download_models(self) -> None:
        self.btn_download_runtime.setEnabled(False)
        self.btn_download_models.setEnabled(False)
        self.runtime_progress.setVisible(True)
        self.runtime_progress.setRange(0, 0)  # model downloads: busy indicator
        config = self._wizard.result_config()
        local_model = config.local_model
        source = config.source_language
        target = config.target_language

        def worker() -> None:
            try:
                local_runtime.download_models(
                    local_model, source, target, status=self._worker_status.emit
                )
            except local_runtime.LocalRuntimeError as exc:
                self._worker_done.emit(False, str(exc))
                return
            except Exception:
                logger.exception("Download modelli locali fallito")
                self._worker_done.emit(False, t("runtime.download_failed"))
                return
            self._worker_done.emit(True, t("settings.models_ready"))

        threading.Thread(target=worker, daemon=True, name="models-download").start()

    def _on_runtime_progress(self, done: int, total: int) -> None:
        if total > 0:
            self.runtime_progress.setRange(0, max(1, total // 1_000_000))
            self.runtime_progress.setValue(done // 1_000_000)
            self.runtime_status_label.setText(
                t(
                    "settings.runtime_downloading",
                    done=done // 1_000_000,
                    total=total // 1_000_000,
                )
            )
        if total and done >= total:
            self._worker_status.emit(t("settings.runtime_extracting"))

    def _on_worker_done(self, ok: bool, message: str) -> None:
        self.runtime_progress.setVisible(False)
        self.btn_download_runtime.setEnabled(True)
        self.btn_download_models.setEnabled(True)
        self._refresh_runtime_state()
        self.runtime_status_label.setText(message)

    def validatePage(self) -> bool:  # noqa: N802 (Qt name)
        # persist entered credentials so the provider/vMix tests can use them
        for account, edit in self._edits.items():
            value = edit.text().strip()
            if not value:
                continue
            try:
                self._wizard.save_credential(account, value)
            except SecretStorageError as exc:
                QMessageBox.warning(self, t("wizard.window_title"), str(exc))
                return False
        return True


class FirstRunWizard(QWizard):
    # (result, (button, result label)) marshalled onto the GUI thread
    _test_done = Signal(object, object)

    def __init__(
        self,
        config: AppConfig,
        devices: list[AudioDevice],
        services: AppServices,
        secret_store: SecretStore | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("wizard.window_title"))
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        # Qt does not translate the navigation buttons on its own
        self.setButtonText(QWizard.WizardButton.BackButton, t("wizard.button.back"))
        self.setButtonText(QWizard.WizardButton.NextButton, t("wizard.button.next"))
        self.setButtonText(QWizard.WizardButton.FinishButton, t("wizard.button.finish"))
        self.setButtonText(QWizard.WizardButton.CancelButton, t("wizard.button.cancel"))
        self._base_config = config
        self._services = services
        self._secret_store = secret_store
        self._test_done.connect(self._on_test_done)

        # 1. Language & provider
        setup_page = QWizardPage()
        setup_page.setTitle(t("wizard.setup.title"))
        setup_layout = QVBoxLayout(setup_page)
        intro = QLabel(t("wizard.setup.intro"))
        intro.setWordWrap(True)
        setup_layout.addWidget(intro)
        setup_form = QFormLayout()
        setup_layout.addLayout(setup_form)
        self.lang_combo = QComboBox()
        for code, name in available_locales().items():
            self.lang_combo.addItem(name, code)
        _select_by_data(self.lang_combo, config.ui_language)
        self.provider_combo = QComboBox()
        for info in available_providers():
            self.provider_combo.addItem(info.display_name, info.id)
        _select_by_data(self.provider_combo, config.provider)
        # spoken/subtitle languages: they drive the provider config AND which
        # models the local-provider download fetches
        self.source_combo = QComboBox()
        self.target_combo = QComboBox()
        for label, code in LANGUAGES:
            self.source_combo.addItem(label, code)
            self.target_combo.addItem(label, code)
        _select_by_data(self.source_combo, config.source_language)
        _select_by_data(self.target_combo, config.target_language)
        setup_form.addRow(t("wizard.setup.language_label"), self.lang_combo)
        setup_form.addRow(t("wizard.setup.provider_label"), self.provider_combo)
        setup_form.addRow(t("wizard.setup.source_label"), self.source_combo)
        setup_form.addRow(t("wizard.setup.target_label"), self.target_combo)
        self.addPage(setup_page)

        # 2. Credentials (dynamic, per selected provider)
        self._credentials_page = _CredentialsPage(self)
        self.addPage(self._credentials_page)

        # 3. Provider test
        page, self.api_test_button, self.api_test_label = self._make_test_page(
            t("wizard.api_test.title"),
            t("wizard.api_test.intro"),
            t("wizard.api_test.button"),
            self._services.test_api,
        )
        self.addPage(page)

        # 4. Audio input
        audio_page = QWizardPage()
        audio_page.setTitle(t("wizard.audio.title"))
        audio_form = QFormLayout(audio_page)
        self.device_combo = QComboBox()
        self.device_combo.addItem(SYSTEM_DEFAULT_DEVICE, None)
        for device in devices:
            self.device_combo.addItem(device.name, device.id)
        _select_by_data(self.device_combo, config.audio.device_id)
        audio_form.addRow(t("wizard.audio.input_label"), self.device_combo)
        self.addPage(audio_page)

        # 5. vMix
        vmix_page = QWizardPage()
        vmix_page.setTitle(t("wizard.vmix.title"))
        vmix_form = QFormLayout(vmix_page)
        self.host_edit = QLineEdit(config.vmix.host)
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(config.vmix.port)
        self.input_edit = QLineEdit(config.vmix.input)
        self.input_edit.setPlaceholderText(t("wizard.vmix.input_placeholder"))
        self.field_edit = QLineEdit(config.vmix.selected_name)
        vmix_form.addRow(t("wizard.vmix.host_label"), self.host_edit)
        vmix_form.addRow(t("wizard.vmix.port_label"), self.port_spin)
        vmix_form.addRow(t("wizard.vmix.input_label"), self.input_edit)
        vmix_form.addRow(t("wizard.vmix.field_label"), self.field_edit)
        self.addPage(vmix_page)

        # 6. vMix test — uses the values just typed in the wizard
        page, self.vmix_test_button, self.vmix_test_label = self._make_test_page(
            t("wizard.vmix_test.title"),
            t("wizard.vmix_test.intro"),
            t("wizard.vmix_test.button"),
            self._services.test_vmix,
        )
        self.addPage(page)

        # 7. Finish
        final_page = QWizardPage()
        final_page.setTitle(t("wizard.final.title"))
        final_layout = QVBoxLayout(final_page)
        final_layout.addWidget(QLabel(t("wizard.final.note")))
        self.addPage(final_page)

    # ------------------------------------------------------------------ credentials

    def save_credential(self, account: str, value: str) -> None:
        if self._secret_store is not None:
            self._secret_store.set_api_key(account, value)

    # ------------------------------------------------------------------ test

    def _make_test_page(
        self, title: str, intro: str, button_text: str, run_test
    ) -> tuple[QWizardPage, QPushButton, QLabel]:
        page = QWizardPage()
        page.setTitle(title)
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel(intro))
        result_label = QLabel("")
        result_label.setWordWrap(True)
        button = QPushButton(button_text)

        def on_click() -> None:
            button.setEnabled(False)
            result_label.setText(t("wizard.test.running"))
            # read the widgets and push config on the GUI thread; the worker
            # thread must only run the (blocking) service call, never touch Qt
            self._services.update_config(self.result_config())

            def runner() -> None:
                try:
                    result = run_test()
                except Exception:
                    logger.exception("Errore inatteso nel test del wizard")
                    result = None
                self._test_done.emit(result, (button, result_label))

            threading.Thread(target=runner, daemon=True, name="wizard-test").start()

        button.clicked.connect(on_click)
        layout.addWidget(button)
        layout.addWidget(result_label)
        layout.addStretch()
        return page, button, result_label

    def _on_test_done(self, result, widgets) -> None:
        button, result_label = widgets
        button.setEnabled(True)
        if result is None:
            result_label.setText(t("wizard.test.unexpected_error"))
        else:
            icon = "✔" if result.ok else "✘"
            result_label.setText(t("wizard.test.result", icon=icon, message=result.message))

    def _run_api_test(self):
        self._services.update_config(self.result_config())
        return self._services.test_api()

    def _run_vmix_test(self):
        self._services.update_config(self.result_config())
        return self._services.test_vmix()

    # ------------------------------------------------------------------ data

    def result_config(self) -> AppConfig:
        config = AppConfig.from_dict(self._base_config.to_dict())
        config.ui_language = self.lang_combo.currentData()
        config.provider = self.provider_combo.currentData()
        config.source_language = self.source_combo.currentData()
        config.target_language = self.target_combo.currentData()
        config.local_model = self._credentials_page.local_model_combo.currentData()
        config.local_device = self._credentials_page.local_device_combo.currentData()
        config.audio.device_id = self.device_combo.currentData()
        config.vmix.host = self.host_edit.text().strip()
        config.vmix.port = self.port_spin.value()
        config.vmix.input = self.input_edit.text().strip()
        config.vmix.selected_name = self.field_edit.text().strip()
        return config
