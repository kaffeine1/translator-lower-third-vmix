# Translator Lower Third for vMix
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""First-run wizard.

Steps: audio input → API key → API test → vMix → vMix test → save and start.
Like the settings dialog, the wizard persists nothing: the caller saves
result_config() and entered_api_key(). The tests (API/vMix) run on worker
threads: HTTP calls must never freeze the wizard.
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
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from app.audio.devices import AudioDevice
from app.config.models import AppConfig
from app.gui.settings_dialog import SYSTEM_DEFAULT_DEVICE, _select_by_data
from app.i18n import t
from app.services import AppServices

logger = logging.getLogger("app.gui")


class FirstRunWizard(QWizard):
    # (result, (button, result label)) marshalled onto the GUI thread
    _test_done = Signal(object, object)

    def __init__(
        self,
        config: AppConfig,
        devices: list[AudioDevice],
        services: AppServices,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("wizard.window_title"))
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        # Qt does not translate the navigation buttons on its own: Italian texts
        self.setButtonText(QWizard.WizardButton.BackButton, t("wizard.button.back"))
        self.setButtonText(QWizard.WizardButton.NextButton, t("wizard.button.next"))
        self.setButtonText(QWizard.WizardButton.FinishButton, t("wizard.button.finish"))
        self.setButtonText(QWizard.WizardButton.CancelButton, t("wizard.button.cancel"))
        self._base_config = config
        self._services = services
        self._test_done.connect(self._on_test_done)

        # 1. Audio input
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

        # 2. API key
        key_page = QWizardPage()
        key_page.setTitle(t("wizard.key.title"))
        key_form = QFormLayout(key_page)
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText(t("wizard.key.placeholder"))
        key_form.addRow(t("wizard.key.label"), self.api_key_edit)
        key_form.addRow(
            QLabel(t("wizard.key.note"))
        )
        self.addPage(key_page)

        # 3. Test API
        page, self.api_test_button, self.api_test_label = self._make_test_page(
            t("wizard.api_test.title"),
            t("wizard.api_test.intro"),
            t("wizard.api_test.button"),
            services.test_api,
        )
        self.addPage(page)

        # 4. vMix
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

        # 5. vMix test — uses the values just typed in the wizard, not the
        # saved config (which does not exist yet at this point)
        page, self.vmix_test_button, self.vmix_test_label = self._make_test_page(
            t("wizard.vmix_test.title"),
            t("wizard.vmix_test.intro"),
            t("wizard.vmix_test.button"),
            self._run_vmix_test,
        )
        self.addPage(page)

        # 6. Finish
        final_page = QWizardPage()
        final_page.setTitle(t("wizard.final.title"))
        final_layout = QVBoxLayout(final_page)
        final_layout.addWidget(
            QLabel(t("wizard.final.note"))
        )
        self.addPage(final_page)

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

    def _run_vmix_test(self):
        self._services.update_config(self.result_config())
        return self._services.test_vmix()

    # ------------------------------------------------------------------ data

    def result_config(self) -> AppConfig:
        config = AppConfig.from_dict(self._base_config.to_dict())
        config.audio.device_id = self.device_combo.currentData()
        config.vmix.host = self.host_edit.text().strip()
        config.vmix.port = self.port_spin.value()
        config.vmix.input = self.input_edit.text().strip()
        config.vmix.selected_name = self.field_edit.text().strip()
        return config

    def entered_api_key(self) -> str:
        return self.api_key_edit.text().strip()
