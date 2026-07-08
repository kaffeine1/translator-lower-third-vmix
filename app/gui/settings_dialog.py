# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""Settings window.

The dialog touches neither disk nor the secret store: it builds an AppConfig
with result_config() and exposes the typed key via entered_api_key(); it is the
caller (MainWindow) that saves. This makes it testable without I/O.
"""

from __future__ import annotations

import importlib.util
import logging
import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app import local_runtime
from app.audio.devices import AudioDevice
from app.config.models import LOCAL_DEVICES, LOCAL_MODELS, AppConfig
from app.gui.subtitle_overlay import available_monitors
from app.i18n import available_locales, t
from app.providers.registry import available_providers, get_provider_info

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


def _format_size(size_bytes: int) -> str:
    """Human size for the operator ('4,3 GB' / '862 MB')."""
    if size_bytes >= 1_000_000_000:
        return f"{size_bytes / 1_000_000_000:.1f} GB".replace(".", ",")
    return f"{size_bytes // 1_000_000} MB"


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


logger = logging.getLogger("app.gui")


class SettingsDialog(QDialog):
    # worker-thread -> GUI marshalling for the local-runtime downloads
    _runtime_progress = Signal(int, int)  # done bytes, total bytes (0 = unknown)
    _worker_status = Signal(str)
    _worker_done = Signal(bool, str)  # ok, operator message

    def __init__(
        self,
        config: AppConfig,
        devices: list[AudioDevice],
        saved_accounts: set[str] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("settings.window_title"))
        self.setMinimumWidth(420)
        # secure-storage accounts that already have a stored value (drives the
        # "already saved" placeholder on each credential field)
        self._saved_accounts = set(saved_accounts or ())
        self._cred_edits: dict[str, QLineEdit] = {}
        self._build_ui(devices)
        self._load(config)

    # ------------------------------------------------------------------ UI

    def _build_ui(self, devices: list[AudioDevice]) -> None:
        # The settings grow with dynamic credential fields and the local-provider
        # group; on short screens they must not push the Save/Cancel buttons off
        # the bottom. So the groups live inside a scroll area and the buttons
        # stay outside it, always visible.
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        # horizontal bar only if the window is ever forced narrower than the
        # fields (very small screens) — normally the width fits and it stays hidden
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        content = QWidget()
        layout = QVBoxLayout(content)

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
        self.source_combo = QComboBox()
        self.target_combo = QComboBox()
        for label, code in LANGUAGES:
            self.source_combo.addItem(label, code)
            self.target_combo.addItem(label, code)
        provider_form.addRow(t("settings.label.provider"), self.provider_combo)
        provider_form.addRow(t("settings.label.source_language"), self.source_combo)
        provider_form.addRow(t("settings.label.target_language"), self.target_combo)
        layout.addWidget(provider_box)

        # credentials: fields depend on the selected provider, rebuilt on change
        credentials_box = QGroupBox(t("settings.group.credentials"))
        self._cred_form = QFormLayout(credentials_box)
        layout.addWidget(credentials_box)
        self.provider_combo.currentIndexChanged.connect(self._rebuild_credentials)

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

        local_box = QGroupBox(t("settings.group.local"))
        local_form = QFormLayout(local_box)
        self.local_model_combo = QComboBox()
        for size in LOCAL_MODELS:
            self.local_model_combo.addItem(size, size)
        self.local_device_combo = QComboBox()
        for code in LOCAL_DEVICES:
            self.local_device_combo.addItem(t(f"settings.device.{code}"), code)
        local_form.addRow(t("settings.label.local_model"), self.local_model_combo)
        local_form.addRow(t("settings.label.local_device"), self.local_device_combo)
        note = QLabel(t("settings.local_hardware_note"))
        note.setWordWrap(True)
        local_form.addRow(note)
        # download & setup of the heavy local components (runtime pack) and of
        # the models: keeps the installer light while making local providers
        # one click away for the operator
        self.runtime_status_label = QLabel()
        # its text can be long (e.g. "…da scaricare (repo1, repo2)"): without
        # wrapping its minimum width forced the dialog ~1500 px wide + a
        # horizontal scrollbar
        self.runtime_status_label.setWordWrap(True)
        local_form.addRow(self.runtime_status_label)
        self.btn_download_runtime = QPushButton()  # label set by _sync_runtime_button_label
        self.btn_download_runtime.setObjectName("btn_download_runtime")
        local_form.addRow(self.btn_download_runtime)
        self.btn_download_models = QPushButton(t("settings.btn_download_models"))
        self.btn_download_models.setObjectName("btn_download_models")
        local_form.addRow(self.btn_download_models)
        # models are hundreds of MB to GBs: after the event they can be removed
        # (and re-downloaded any time)
        self.btn_remove_models = QPushButton(t("settings.btn_remove_models"))
        self.btn_remove_models.setObjectName("btn_remove_models")
        local_form.addRow(self.btn_remove_models)
        self.runtime_progress = QProgressBar()
        self.runtime_progress.setVisible(False)
        local_form.addRow(self.runtime_progress)
        self.btn_download_runtime.clicked.connect(self._on_download_runtime)
        self.btn_download_models.clicked.connect(self._on_download_models)
        self.btn_remove_models.clicked.connect(self._on_remove_models)
        self._runtime_progress.connect(self._on_runtime_progress)
        self._worker_status.connect(self.runtime_status_label.setText)
        self._worker_done.connect(self._on_worker_done)
        # changing the local model or the languages must be reflected in the
        # status hint: the next "download models" fetches the NEW selection
        self.local_model_combo.currentIndexChanged.connect(self._refresh_models_state)
        self.source_combo.currentIndexChanged.connect(self._refresh_models_state)
        self.target_combo.currentIndexChanged.connect(self._refresh_models_state)
        # switching CPU<->GPU changes which pack is needed (and its size): the
        # status flips to "da scaricare" and the button shows the GPU size
        self.local_device_combo.currentIndexChanged.connect(self._on_device_changed)
        self._sync_runtime_button_label()
        self._refresh_runtime_state()
        layout.addWidget(local_box)

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

        overlay_box = QGroupBox(t("settings.group.overlay"))
        overlay_form = QFormLayout(overlay_box)
        self.overlay_enabled_check = QCheckBox(t("settings.overlay.enabled_text"))
        self.overlay_monitor_combo = QComboBox()
        for mon in available_monitors():
            suffix = t("settings.overlay.primary_suffix") if mon.primary else ""
            label = t(
                "settings.overlay.monitor_item",
                n=mon.index + 1,
                w=mon.width,
                h=mon.height,
                suffix=suffix,
            )
            self.overlay_monitor_combo.addItem(label, mon.name)
        self.overlay_font_spin = QSpinBox()
        self.overlay_font_spin.setRange(8, 200)
        self.overlay_font_spin.setSuffix(" pt")
        self.overlay_opacity_spin = QSpinBox()
        self.overlay_opacity_spin.setRange(0, 255)
        overlay_form.addRow(t("settings.label.overlay_enabled"), self.overlay_enabled_check)
        overlay_form.addRow(t("settings.label.overlay_monitor"), self.overlay_monitor_combo)
        overlay_form.addRow(t("settings.label.overlay_font"), self.overlay_font_spin)
        overlay_form.addRow(t("settings.label.overlay_opacity"), self.overlay_opacity_spin)
        overlay_note = QLabel(t("settings.overlay.note"))
        overlay_note.setWordWrap(True)
        overlay_form.addRow(overlay_note)
        layout.addWidget(overlay_box)

        layout.addStretch()
        # A combo defaults to demanding the width of its LONGEST item as its
        # minimum (e.g. a long audio-device name forced ~714 px), which made the
        # content ~1554 px wide and produced a horizontal scrollbar. Let every
        # combo shrink instead (it elides the current text; the popup still shows
        # full items): the fields still stretch to the form width, but no longer
        # dictate the dialog width.
        for combo in content.findChildren(QComboBox):
            combo.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            combo.setMinimumContentsLength(16)

        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(t("settings.button.save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t("settings.button.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        # Open wide enough to show the content without a horizontal scrollbar.
        # The viewport width = dialog width - the dialog's own layout margins -
        # the vertical scrollbar; it must be >= the content's required width, so
        # add ALL of that chrome (the previous +4 ignored the ~22 px dialog
        # margins, leaving the fields a hair too narrow). Never exceed the
        # available screen (so the buttons stay reachable).
        hint = content.sizeHint()
        needed = max(hint.width(), content.minimumSizeHint().width())
        vbar_w = scroll.verticalScrollBar().sizeHint().width()
        margins = outer.contentsMargins()
        chrome = vbar_w + margins.left() + margins.right() + 4
        screen = self.screen() or QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        avail_h = avail.height() if avail else 900
        avail_w = avail.width() if avail else 1200
        max_h = max(360, avail_h - 80)
        width = max(self.minimumWidth(), needed + chrome)
        self.setMaximumHeight(max_h)
        self.resize(min(width, avail_w - 40), min(hint.height() + 90, max_h))

    # ------------------------------------------------------------------ data

    def _rebuild_credentials(self) -> None:
        """Show one field per credential required by the selected provider."""
        while self._cred_form.rowCount():
            self._cred_form.removeRow(0)
        self._cred_edits.clear()
        info = get_provider_info(self.provider_combo.currentData())
        credentials = info.credentials if info else ()
        if not credentials:
            self._cred_form.addRow(QLabel(t("settings.credentials_none")))
            return
        for cred in credentials:
            edit = QLineEdit()
            if cred.secret:
                edit.setEchoMode(QLineEdit.EchoMode.Password)
            edit.setPlaceholderText(
                t("cred.placeholder_saved")
                if cred.account in self._saved_accounts
                else t("cred.placeholder_new")
            )
            self._cred_form.addRow(t(cred.label_key), edit)
            self._cred_edits[cred.account] = edit

    def _load(self, config: AppConfig) -> None:
        _select_by_data(self.lang_combo, config.ui_language)
        _select_by_data(self.provider_combo, config.provider)
        self._rebuild_credentials()  # match the selected provider
        _select_by_data(self.local_model_combo, config.local_model)
        _select_by_data(self.local_device_combo, config.local_device)
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
        self.overlay_enabled_check.setChecked(config.overlay.enabled)
        self._select_overlay_monitor(config.overlay.monitor)
        self.overlay_font_spin.setValue(config.overlay.font_point_size)
        self.overlay_opacity_spin.setValue(config.overlay.background_opacity)
        self._base_config = config

    def _select_overlay_monitor(self, name: str) -> None:
        # match the saved screen; empty or disconnected -> primary (else first)
        index = self.overlay_monitor_combo.findData(name) if name else -1
        if index < 0:
            index = next(
                (m.index for m in available_monitors() if m.primary), 0
            )
        self.overlay_monitor_combo.setCurrentIndex(
            index if index < self.overlay_monitor_combo.count() else 0
        )

    def result_config(self) -> AppConfig:
        config = AppConfig.from_dict(self._base_config.to_dict())
        config.ui_language = self.lang_combo.currentData()
        config.provider = self.provider_combo.currentData()
        config.local_model = self.local_model_combo.currentData()
        config.local_device = self.local_device_combo.currentData()
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
        config.overlay.enabled = self.overlay_enabled_check.isChecked()
        config.overlay.monitor = self.overlay_monitor_combo.currentData() or ""
        config.overlay.font_point_size = self.overlay_font_spin.value()
        config.overlay.background_opacity = self.overlay_opacity_spin.value()
        return config

    def entered_credentials(self) -> dict[str, str]:
        """account -> value for credential fields the user filled.

        Empty fields are omitted (leave the stored value unchanged)."""
        return {
            account: edit.text().strip()
            for account, edit in self._cred_edits.items()
            if edit.text().strip()
        }

    # ------------------------------------------------------------ local runtime

    def _selected_device(self) -> str:
        return self.local_device_combo.currentData()

    def _local_components_available(self) -> bool:
        """True when the components for the SELECTED device are usable: the pack
        for that device is installed, or (dev environment, no pack at all) the
        packages are importable. A CPU-only install must not read as ready when
        GPU is selected — the GPU pack is a different download."""
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
        device = self._selected_device()
        size_bytes = local_runtime.pack_for(device).size_bytes
        size_text = f"{size_bytes // 1_000_000} MB" if size_bytes else "1 GB"
        # when a pack is already marked installed the button becomes a repair
        # (re-download): the marker can outlive the files, and there must always
        # be a way to fetch them again
        key = (
            "settings.btn_redownload_runtime"
            if local_runtime.is_installed(device=device)
            else "settings.btn_download_runtime"
        )
        self.btn_download_runtime.setText(t(key, size=size_text))

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
        # always offer the download/repair button (see _sync_runtime_button_label):
        # a pack can look installed via a stale marker yet fail to import, and the
        # operator must still be able to re-fetch it
        self.btn_download_runtime.setVisible(True)
        self._sync_runtime_button_label()
        self.btn_download_models.setEnabled(available)
        self.btn_remove_models.setEnabled(bool(local_runtime.downloaded_models()))
        if available:
            self._refresh_models_state()

    def _refresh_models_state(self) -> None:
        """Reflect whether the models for the CURRENT model/language selection
        are already downloaded: after changing the local model or the languages
        it must be clear that the next download fetches the new selection."""
        if not self._local_components_available():
            return
        local_model = self.local_model_combo.currentData()
        source = self.source_combo.currentData()
        target = self.target_combo.currentData()
        cached = local_runtime.models_cached(local_model, source, target)
        if cached is None:
            return
        if cached:
            self.runtime_status_label.setText(t("settings.models_state_present"))
        else:
            names = ", ".join(
                local_runtime.required_model_repos(local_model, source, target)
            )
            self.runtime_status_label.setText(
                t("settings.models_state_missing", names=names)
            )

    def _on_download_runtime(self) -> None:
        self.btn_download_runtime.setEnabled(False)
        self.btn_download_models.setEnabled(False)
        self.btn_remove_models.setEnabled(False)
        self.runtime_progress.setVisible(True)
        self.runtime_progress.setRange(0, 0)  # busy until the size is known
        device = self._selected_device()

        # if the pack already looks installed, this click is a repair: force a
        # fresh download rather than short-circuiting on the (possibly stale) marker
        force = local_runtime.is_installed(device=device)

        def worker() -> None:
            try:
                local_runtime.download_and_install(
                    device=device,
                    force=force,
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
        # removing models while a download is writing them would kill the
        # download with an opaque OSError: one operation at a time
        self.btn_download_runtime.setEnabled(False)
        self.btn_download_models.setEnabled(False)
        self.btn_remove_models.setEnabled(False)
        self.runtime_progress.setVisible(True)
        self.runtime_progress.setRange(0, 0)  # model downloads: busy indicator
        local_model = self.local_model_combo.currentData()
        source = self.source_combo.currentData()
        target = self.target_combo.currentData()

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

    def _on_remove_models(self) -> None:
        models = local_runtime.downloaded_models()
        if not models:
            return
        total = sum(model.size_bytes for model in models)
        answer = QMessageBox.question(
            self,
            t("settings.remove_models_title"),
            t("settings.remove_models_confirm", count=len(models), size=_format_size(total)),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.btn_download_runtime.setEnabled(False)
        self.btn_download_models.setEnabled(False)
        self.btn_remove_models.setEnabled(False)

        def worker() -> None:
            try:
                freed, failed = local_runtime.remove_downloaded_models()
            except Exception:
                logger.exception("Rimozione modelli fallita")
                self._worker_done.emit(False, t("runtime.download_failed"))
                return
            if failed:
                message = t(
                    "settings.remove_models_partial",
                    size=_format_size(freed),
                    names=", ".join(failed),
                )
            else:
                message = t("settings.remove_models_done", size=_format_size(freed))
            self._worker_done.emit(not failed, message)

        threading.Thread(target=worker, daemon=True, name="models-remove").start()

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
