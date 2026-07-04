# Translator Lower Third for vMix
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""Settings window.

The dialog touches neither disk nor the secret store: it builds an AppConfig
with result_config() and exposes the typed key via entered_api_key(); it is the
caller (MainWindow) that saves. This makes it testable without I/O.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from app.audio.devices import AudioDevice
from app.config.models import AppConfig
from app.i18n import available_locales, t
from app.providers.registry import available_providers

LANGUAGES = [
    ("Spagnolo", "es"),
    ("Italiano", "it"),
    ("Inglese", "en"),
    ("Francese", "fr"),
    ("Portoghese", "pt"),
]

# Populated from the provider registry: (display name, id).
PROVIDERS = [(info.display_name, info.id) for info in available_providers()]

SYSTEM_DEFAULT_DEVICE = t("settings.system_default_device")


def _select_by_data(combo: QComboBox, data: object) -> None:
    """Selects the entry with the given data.

    If the saved value is not in the list (disconnected device, config
    edited by hand) an entry is added that preserves it: saving without
    touching the dropdown must never silently rewrite the value.
    """
    index = combo.findData(data)
    if index < 0 and data is not None:
        combo.addItem(t("settings.device_not_in_list", data=data), data)
        index = combo.count() - 1
    combo.setCurrentIndex(index if index >= 0 else 0)


class SettingsDialog(QDialog):
    def __init__(
        self,
        config: AppConfig,
        devices: list[AudioDevice],
        has_saved_api_key: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("settings.window_title"))
        self.setMinimumWidth(420)
        self._build_ui(devices)
        self._load(config, has_saved_api_key)

    # ------------------------------------------------------------------ UI

    def _build_ui(self, devices: list[AudioDevice]) -> None:
        layout = QVBoxLayout(self)

        interface_box = QGroupBox(t("settings.group.interface"))
        interface_form = QFormLayout(interface_box)
        self.lang_combo = QComboBox()
        for code, name in available_locales().items():
            self.lang_combo.addItem(name, code)
        interface_form.addRow(t("settings.label.ui_language"), self.lang_combo)
        layout.addWidget(interface_box)

        provider_box = QGroupBox(t("settings.group.provider"))
        provider_form = QFormLayout(provider_box)
        self.provider_combo = QComboBox()
        for label, code in PROVIDERS:
            self.provider_combo.addItem(label, code)
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.source_combo = QComboBox()
        self.target_combo = QComboBox()
        for label, code in LANGUAGES:
            self.source_combo.addItem(label, code)
            self.target_combo.addItem(label, code)
        provider_form.addRow(t("settings.label.provider"), self.provider_combo)
        provider_form.addRow(t("settings.label.api_key"), self.api_key_edit)
        provider_form.addRow(t("settings.label.source_language"), self.source_combo)
        provider_form.addRow(t("settings.label.target_language"), self.target_combo)
        layout.addWidget(provider_box)

        audio_box = QGroupBox(t("settings.group.audio"))
        audio_form = QFormLayout(audio_box)
        self.device_combo = QComboBox()
        self.device_combo.addItem(SYSTEM_DEFAULT_DEVICE, None)
        for device in devices:
            self.device_combo.addItem(device.name, device.id)
        audio_form.addRow(t("settings.label.audio_input"), self.device_combo)
        layout.addWidget(audio_box)

        vmix_box = QGroupBox(t("settings.group.vmix"))
        vmix_form = QFormLayout(vmix_box)
        self.host_edit = QLineEdit()
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText(t("settings.vmix.input_placeholder"))
        self.field_edit = QLineEdit()
        vmix_form.addRow(t("settings.label.vmix_host"), self.host_edit)
        vmix_form.addRow(t("settings.label.vmix_port"), self.port_spin)
        vmix_form.addRow(t("settings.label.vmix_input"), self.input_edit)
        vmix_form.addRow(t("settings.label.vmix_field"), self.field_edit)
        layout.addWidget(vmix_box)

        subtitles_box = QGroupBox(t("settings.group.subtitles"))
        subtitles_form = QFormLayout(subtitles_box)
        self.chars_spin = QSpinBox()
        self.chars_spin.setRange(8, 120)
        self.lines_spin = QSpinBox()
        self.lines_spin.setRange(1, 4)
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(0, 10000)
        self.interval_spin.setSingleStep(100)
        self.interval_spin.setSuffix(" ms")
        self.hold_spin = QSpinBox()
        self.hold_spin.setRange(0, 60)
        self.hold_spin.setSuffix(" s")
        self.clear_spin = QSpinBox()
        self.clear_spin.setRange(0, 120)
        self.clear_spin.setSuffix(" s")
        subtitles_form.addRow(t("settings.label.max_chars"), self.chars_spin)
        subtitles_form.addRow(t("settings.label.max_lines"), self.lines_spin)
        subtitles_form.addRow(t("settings.label.min_interval"), self.interval_spin)
        subtitles_form.addRow(t("settings.label.hold"), self.hold_spin)
        subtitles_form.addRow(t("settings.label.clear_silence"), self.clear_spin)
        layout.addWidget(subtitles_box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(t("settings.button.save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t("settings.button.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------ data

    def _load(self, config: AppConfig, has_saved_api_key: bool) -> None:
        _select_by_data(self.lang_combo, config.ui_language)
        _select_by_data(self.provider_combo, config.provider)
        # the saved key is never shown: empty field = do not change
        self.api_key_edit.setPlaceholderText(
            t("settings.api_key.placeholder_saved")
            if has_saved_api_key
            else t("settings.api_key.placeholder_new")
        )
        _select_by_data(self.source_combo, config.source_language)
        _select_by_data(self.target_combo, config.target_language)
        _select_by_data(self.device_combo, config.audio.device_id)
        self.host_edit.setText(config.vmix.host)
        self.port_spin.setValue(config.vmix.port)
        self.input_edit.setText(config.vmix.input)
        self.field_edit.setText(config.vmix.selected_name)
        self.chars_spin.setValue(config.subtitles.max_chars_per_line)
        self.lines_spin.setValue(config.subtitles.max_lines)
        self.interval_spin.setValue(config.subtitles.min_update_interval_ms)
        self.hold_spin.setValue(config.subtitles.hold_seconds)
        self.clear_spin.setValue(config.subtitles.clear_after_silence_seconds)
        self._base_config = config

    def result_config(self) -> AppConfig:
        config = AppConfig.from_dict(self._base_config.to_dict())
        config.ui_language = self.lang_combo.currentData()
        config.provider = self.provider_combo.currentData()
        config.source_language = self.source_combo.currentData()
        config.target_language = self.target_combo.currentData()
        config.audio.device_id = self.device_combo.currentData()
        config.vmix.host = self.host_edit.text().strip()
        config.vmix.port = self.port_spin.value()
        config.vmix.input = self.input_edit.text().strip()
        config.vmix.selected_name = self.field_edit.text().strip()
        config.subtitles.max_chars_per_line = self.chars_spin.value()
        config.subtitles.max_lines = self.lines_spin.value()
        config.subtitles.min_update_interval_ms = self.interval_spin.value()
        config.subtitles.hold_seconds = self.hold_spin.value()
        config.subtitles.clear_after_silence_seconds = self.clear_spin.value()
        return config

    def entered_api_key(self) -> str:
        """Key typed by the user; empty string = do not change the saved one."""
        return self.api_key_edit.text().strip()
