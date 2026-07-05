# Translator Lower Third for vMix
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

import logging
import threading

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from app.audio.devices import AudioDevice
from app.config.models import AppConfig
from app.config.secrets import SecretStorageError, SecretStore
from app.gui.settings_dialog import SYSTEM_DEFAULT_DEVICE, _select_by_data
from app.i18n import available_locales, t
from app.providers.registry import available_providers, get_provider_info
from app.services import AppServices

logger = logging.getLogger("app.gui")


class _CredentialsPage(QWizardPage):
    """Shows one field per credential the selected provider needs and saves them
    to secure storage when advancing (so the following tests can use them)."""

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

    def initializePage(self) -> None:  # noqa: N802 (Qt name)
        while self._form.rowCount():
            self._form.removeRow(0)
        self._edits.clear()
        info = get_provider_info(self._wizard.provider_combo.currentData())
        credentials = info.credentials if info else ()
        if not credentials:
            self._form.addRow(QLabel(t("wizard.credentials.none")))
            return
        for cred in credentials:
            edit = QLineEdit()
            if cred.secret:
                edit.setEchoMode(QLineEdit.EchoMode.Password)
            self._form.addRow(t(cred.label_key), edit)
            self._edits[cred.account] = edit

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
        setup_form.addRow(t("wizard.setup.language_label"), self.lang_combo)
        setup_form.addRow(t("wizard.setup.provider_label"), self.provider_combo)
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
        config.audio.device_id = self.device_combo.currentData()
        config.vmix.host = self.host_edit.text().strip()
        config.vmix.port = self.port_spin.value()
        config.vmix.input = self.input_edit.text().strip()
        config.vmix.selected_name = self.field_edit.text().strip()
        return config
