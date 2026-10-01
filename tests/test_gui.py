# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""GUI tests (Milestone 2) — run headless with the Qt offscreen platform."""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6", reason="PySide6 non installato")

from PySide6.QtWidgets import QApplication

from app.config.manager import ConfigManager
from app.config.models import AppConfig
from app.config.secrets import InMemorySecretStore
from app.gui.first_run_wizard import FirstRunWizard
from app.gui.main_window import MainWindow
from app.gui.settings_dialog import SettingsDialog
from app.gui.widgets import StatusLight, StatusState, SubtitlePreview
from app.services import MockAppServices


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def local_visible(monkeypatch):
    """The local (offline) providers are hidden from the GUI by default: the
    tests of their controls run with them shown, as when re-enabled."""
    import app.providers.registry as registry

    monkeypatch.setattr(registry, "LOCAL_PROVIDERS_VISIBLE", True)


def _make_window(tmp_path, services=None, store=None):
    manager = ConfigManager(config_dir=tmp_path)
    config = manager.load()
    return MainWindow(
        manager, config, services or MockAppServices(), store or InMemorySecretStore()
    )


def _process_until(qapp, predicate, timeout_s=3.0) -> bool:
    """Pump Qt events until predicate() is true (for async outcomes)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    return False


# ---------------------------------------------------------------- widgets


def test_status_light_states(qapp):
    light = StatusLight()
    assert light.state == StatusState.YELLOW
    light.set_state(StatusState.GREEN)
    assert light.state == StatusState.GREEN
    light.set_state(StatusState.RED)
    assert light.state == StatusState.RED


def test_subtitle_preview_placeholder(qapp):
    preview = SubtitlePreview()
    assert preview.text() == ""
    preview.set_text("Ciao mondo")
    assert preview.text() == "Ciao mondo"


# ---------------------------------------------------------------- main window


def test_main_window_has_required_controls(qapp, tmp_path):
    window = _make_window(tmp_path)
    assert window.btn_start.text() == "START"
    assert window.btn_stop.text() == "STOP"
    assert window.btn_test_audio.text() == "Test Audio"
    assert window.btn_test_api.text() == "Test API"
    assert window.btn_test_vmix.text() == "Test vMix"
    assert window.btn_settings.text() == "Impostazioni"
    assert window.btn_open_log.text() == "Apri Log"
    assert window.btn_info.text() == "Info"
    for light in (window.audio_light, window.api_light, window.vmix_light):
        assert light.state == StatusState.YELLOW


def test_start_stop_toggle_buttons(qapp, tmp_path):
    # START/STOP run on a worker thread: the outcome arrives asynchronously
    window = _make_window(tmp_path)
    assert window.btn_start.isEnabled()
    assert not window.btn_stop.isEnabled()
    window.btn_start.click()
    assert _process_until(qapp, lambda: window.btn_stop.isEnabled())
    assert not window.btn_start.isEnabled()
    window.btn_stop.click()
    assert _process_until(qapp, lambda: window.btn_start.isEnabled())
    assert not window.btn_stop.isEnabled()


def test_start_updates_subtitle_preview(qapp, tmp_path):
    window = _make_window(tmp_path)
    window.btn_start.click()
    assert _process_until(qapp, lambda: "demo" in window.preview.text())


def test_start_and_stop_do_not_freeze_the_window(qapp, tmp_path):
    # regression (live show 18/09): a slow provider connection or an unreachable
    # vMix froze the window for up to 10 s on START/STOP ("Not responding")
    import threading

    release = threading.Event()

    class SlowServices(MockAppServices):
        def start_translation(self):
            release.wait(timeout=3)
            return super().start_translation()

        def stop_translation(self):
            release.wait(timeout=3)
            return super().stop_translation()

    services = SlowServices()
    window = _make_window(tmp_path, services=services)
    window.btn_start.click()  # returns at once: the call runs on a worker
    qapp.processEvents()
    # while the START is in flight nothing can start it twice or interfere
    assert not window.btn_start.isEnabled()
    assert not window.btn_stop.isEnabled()
    assert not window.btn_settings.isEnabled()
    assert not window.btn_test_audio.isEnabled()
    assert "avvio" in window.statusBar().currentMessage().lower()
    release.set()
    assert _process_until(qapp, lambda: window.btn_stop.isEnabled())
    assert window.btn_settings.isEnabled()
    # the audio test would steal the capture device of the running translation
    assert not window.btn_test_audio.isEnabled()

    release.clear()
    window.btn_stop.click()
    qapp.processEvents()
    assert not window.btn_start.isEnabled()
    assert not window.btn_stop.isEnabled()
    assert "arresto" in window.statusBar().currentMessage().lower()
    release.set()
    assert _process_until(qapp, lambda: window.btn_start.isEnabled())
    assert window.btn_test_audio.isEnabled()
    assert services.running is False


def test_failed_start_leaves_start_available(qapp, tmp_path):
    from app.services import ServiceResult

    class FailingServices(MockAppServices):
        def start_translation(self):
            return ServiceResult(False, "Il servizio di traduzione non risponde.")

    window = _make_window(tmp_path, services=FailingServices())
    window.btn_start.click()
    assert _process_until(
        qapp, lambda: "non risponde" in window.statusBar().currentMessage()
    )
    assert window.btn_start.isEnabled()
    assert not window.btn_stop.isEnabled()


def test_close_waits_for_inflight_start_and_stops_translation(qapp, tmp_path):
    # a START still connecting when the window closes must not leave a
    # translation running with nobody to stop it
    import threading

    release = threading.Event()

    class SlowServices(MockAppServices):
        def start_translation(self):
            release.wait(timeout=3)
            return super().start_translation()

    services = SlowServices()
    window = _make_window(tmp_path, services=services)
    window.btn_start.click()
    threading.Timer(0.2, release.set).start()
    window.close()
    assert services.running is False


def test_diagnostics_text_has_version_and_paths_no_secret(qapp, tmp_path):
    from app import __version__

    store = InMemorySecretStore()
    store.set_api_key("openai", "sk-supersegretissima-123456789")
    window = _make_window(tmp_path, store=store)
    text = window.diagnostics_text()
    assert __version__ in text
    assert "TranslatorLowerThird" in text  # config/log paths
    assert "Chiave API salvata: sì" in text
    # the About shows the author and the essential info
    assert "Michele Dipace" in text
    assert "michele.dipace@kaffeine.net" in text
    # the plaintext key must never appear in the Info/About screen
    assert "supersegretissima" not in text


def test_translation_error_shown_without_modal(qapp, tmp_path):
    # live errors end up in the status bar and in the status light of the
    # failing link, without modal dialogs that would interrupt the event
    from app.services import STATUS_VMIX

    window = _make_window(tmp_path)
    window.audio_light.set_state(StatusState.GREEN)
    window._services._emit_error("vMix non raggiungibile")
    window._services._emit_status(STATUS_VMIX, False)
    qapp.processEvents()
    assert window.vmix_light.state == StatusState.RED
    assert window.audio_light.state == StatusState.GREEN
    assert "vmix non raggiungibile" in window.statusBar().currentMessage().lower()


def test_provider_error_turns_api_light_red_not_vmix(qapp, tmp_path):
    # regression: a dropped OpenAI connection used to turn the vMix light red
    from app.services import STATUS_API

    window = _make_window(tmp_path)
    window.vmix_light.set_state(StatusState.GREEN)
    window._services._emit_error("Connessione persa, riprovo…")
    window._services._emit_status(STATUS_API, False)
    qapp.processEvents()
    assert window.api_light.state == StatusState.RED
    assert window.vmix_light.state == StatusState.GREEN


def test_link_recovery_turns_light_green_with_message(qapp, tmp_path):
    from app.services import STATUS_API, STATUS_VMIX

    window = _make_window(tmp_path)
    window._services._emit_status(STATUS_API, False)
    window._services._emit_status(STATUS_VMIX, False)
    qapp.processEvents()
    window._services._emit_status(STATUS_API, True, "Connessione ripristinata")
    window._services._emit_status(STATUS_VMIX, True)
    qapp.processEvents()
    assert window.api_light.state == StatusState.GREEN
    assert window.vmix_light.state == StatusState.GREEN
    assert "ripristinata" in window.statusBar().currentMessage().lower()


def test_test_buttons_update_lights(qapp, tmp_path):
    # Test API and Test vMix run on worker threads: the outcome arrives
    # asynchronously on the GUI thread
    services = MockAppServices()
    window = _make_window(tmp_path, services=services)

    window.btn_test_api.click()
    assert _process_until(qapp, lambda: window.api_light.state == StatusState.GREEN)
    assert window.btn_test_api.isEnabled()

    services.fail_vmix = True
    window.btn_test_vmix.click()
    assert _process_until(qapp, lambda: window.vmix_light.state == StatusState.RED)
    assert window.btn_test_vmix.isEnabled()


def test_async_exception_reenables_button_and_clears_status(qapp, tmp_path, monkeypatch):
    # regression: if the service raises, the button becomes active again, the
    # status light goes red and the status bar does not stay on "in corso…"
    from PySide6.QtWidgets import QMessageBox

    class ExplodingServices(MockAppServices):
        def test_vmix(self):
            raise RuntimeError("boom")

    shown = {}
    monkeypatch.setattr(
        QMessageBox, "critical", staticmethod(lambda *a, **k: shown.setdefault("critical", True))
    )
    window = _make_window(tmp_path, services=ExplodingServices())
    window.btn_test_vmix.click()
    assert _process_until(qapp, lambda: window.btn_test_vmix.isEnabled())
    assert shown.get("critical") is True
    assert window.vmix_light.state == StatusState.RED
    assert "in corso" not in window.statusBar().currentMessage().lower()


def test_settings_change_resets_only_affected_status_light(qapp, tmp_path):
    window = _make_window(tmp_path)
    for light in (window.audio_light, window.api_light, window.vmix_light):
        light.set_state(StatusState.GREEN)

    # change ONLY vMix: its light invalidates, Audio/API stay green
    new_config = AppConfig()
    new_config.vmix.input = "Sottopancia"
    assert window._apply_settings(new_config, {}) is True
    assert window.vmix_light.state == StatusState.YELLOW
    assert window.audio_light.state == StatusState.GREEN
    assert window.api_light.state == StatusState.GREEN


def test_settings_change_subtitles_keeps_all_status_lights(qapp, tmp_path):
    # editing subtitles/overlay must not wipe green Audio/API/vMix results
    window = _make_window(tmp_path)
    for light in (window.audio_light, window.api_light, window.vmix_light):
        light.set_state(StatusState.GREEN)

    new_config = AppConfig()
    new_config.subtitles.max_lines = 1
    new_config.subtitles.max_chars_per_line = 100
    assert window._apply_settings(new_config, {}) is True
    for light in (window.audio_light, window.api_light, window.vmix_light):
        assert light.state == StatusState.GREEN


def test_async_test_disables_button_while_running(qapp, tmp_path):
    import threading

    release = threading.Event()

    class SlowServices(MockAppServices):
        def test_vmix(self):
            release.wait(timeout=3)
            return super().test_vmix()

    window = _make_window(tmp_path, services=SlowServices())
    window.btn_test_vmix.click()
    # the GUI stays responsive and the button is disabled during the call
    qapp.processEvents()
    assert not window.btn_test_vmix.isEnabled()
    release.set()
    assert _process_until(qapp, lambda: window.btn_test_vmix.isEnabled())
    assert window.vmix_light.state == StatusState.GREEN


def test_audio_test_toggle_detects_signal(qapp, tmp_path):
    services = MockAppServices()  # default mock_levels above threshold
    window = _make_window(tmp_path, services=services)

    window.btn_test_audio.click()  # start the monitor
    qapp.processEvents()
    assert services.monitoring is True
    assert window.btn_test_audio.text() == "Ferma Test"

    window.btn_test_audio.click()  # stop the monitor
    assert services.monitoring is False
    assert window.btn_test_audio.text() == "Test Audio"
    assert window.audio_light.state == StatusState.GREEN
    assert "audio rilevato" in window.statusBar().currentMessage().lower()


def test_audio_test_silence_reports_no_audio(qapp, tmp_path):
    services = MockAppServices()
    services.mock_levels = (0.0, 0.0)
    window = _make_window(tmp_path, services=services)

    window.btn_test_audio.click()
    qapp.processEvents()
    window.btn_test_audio.click()
    assert window.audio_light.state == StatusState.RED
    assert "nessun audio" in window.statusBar().currentMessage().lower()


def test_audio_test_failure_shows_red_light(qapp, tmp_path):
    services = MockAppServices()
    services.fail_audio = True
    window = _make_window(tmp_path, services=services)
    window.btn_test_audio.click()
    assert window.audio_light.state == StatusState.RED
    assert services.monitoring is False
    assert window.btn_test_audio.text() == "Test Audio"


def test_start_while_audio_testing_stops_monitor(qapp, tmp_path):
    services = MockAppServices()
    window = _make_window(tmp_path, services=services)
    window.btn_test_audio.click()
    qapp.processEvents()
    assert services.monitoring is True
    window.btn_start.click()
    assert services.monitoring is False
    assert _process_until(qapp, lambda: services.running is True)


def test_audio_test_auto_stops_via_timer(qapp, tmp_path):
    services = MockAppServices()
    window = _make_window(tmp_path, services=services)

    window.btn_test_audio.click()
    qapp.processEvents()
    timer = window._audio_test_timer
    assert timer.isActive()
    assert timer.isSingleShot()
    assert timer.interval() == 5000

    timer.timeout.emit()  # trigger the timeout without waiting 5 real seconds
    assert services.monitoring is False
    assert window.btn_test_audio.text() == "Test Audio"
    assert window.audio_light.state == StatusState.GREEN
    assert not timer.isActive()


def test_stale_levels_after_test_end_do_not_touch_meter(qapp, tmp_path):
    # regression: with real audio the levels arrive queued from the
    # PortAudio thread and may be delivered AFTER the end of the test
    services = MockAppServices()
    window = _make_window(tmp_path, services=services)
    window.btn_test_audio.click()
    qapp.processEvents()
    window.btn_test_audio.click()  # end of test: meter reset to zero
    assert window.level_meter.value() == 0

    window.audio_level.emit(0.5)  # "in-flight" level delivered late
    qapp.processEvents()
    assert window.level_meter.value() == 0


# ---------------------------------------------------------------- settings dialog


def _custom_config() -> AppConfig:
    config = AppConfig()
    config.source_language = "es"
    config.target_language = "it"
    config.audio.device_id = 1
    config.vmix.host = "192.168.1.50"
    config.vmix.port = 9000
    config.vmix.input = "Sottopancia"
    config.vmix.selected_name = "Titolo.Text"
    config.subtitles.max_chars_per_line = 36
    config.subtitles.max_lines = 1
    return config


def test_settings_dialog_loads_config(qapp):
    config = _custom_config()
    dialog = SettingsDialog(config, MockAppServices().list_audio_devices())
    assert dialog.host_edit.text() == "192.168.1.50"
    assert dialog.port_spin.value() == 9000
    assert dialog.input_edit.text() == "Sottopancia"
    assert dialog.field_edit.text() == "Titolo.Text"
    assert dialog.chars_spin.value() == 36
    assert dialog.lines_spin.value() == 1
    # OpenAI detects the spoken language: shown as automatic, saved unchanged
    assert dialog.source_combo.currentData() == "auto"
    assert dialog.result_config().source_language == "es"
    assert dialog.target_combo.currentData() == "it"
    assert dialog.device_combo.currentData() == 1


def test_settings_dialog_roundtrip(qapp):
    dialog = SettingsDialog(AppConfig(), MockAppServices().list_audio_devices())
    dialog.host_edit.setText("10.0.0.5")
    dialog.port_spin.setValue(8100)
    dialog.input_edit.setText("Lower3rd")
    dialog.chars_spin.setValue(50)

    result = dialog.result_config()
    assert result.vmix.host == "10.0.0.5"
    assert result.vmix.port == 8100
    assert result.vmix.input == "Lower3rd"
    assert result.subtitles.max_chars_per_line == 50
    # untouched values preserved
    assert result.provider == "openai"
    assert result.subtitles.max_lines == 2


def test_settings_dialog_has_ui_language_selector(qapp):
    dialog = SettingsDialog(AppConfig(), MockAppServices().list_audio_devices())
    # defaults to Italian; result_config carries it through
    assert dialog.lang_combo.currentData() == "it"
    assert dialog.result_config().ui_language == "it"


def test_settings_dialog_buttons_stay_outside_scroll_area(qapp):
    # On short screens the settings must scroll while Save/Cancel stay visible:
    # the fields live inside a QScrollArea, the buttons outside it.
    from PySide6.QtWidgets import QDialogButtonBox, QScrollArea

    dialog = SettingsDialog(AppConfig(), MockAppServices().list_audio_devices())

    scroll = dialog.findChild(QScrollArea)
    assert scroll is not None
    buttons = dialog.findChild(QDialogButtonBox)
    assert buttons is not None

    def _inside(widget, ancestor) -> bool:
        node = widget.parentWidget()
        while node is not None:
            if node is ancestor:
                return True
            node = node.parentWidget()
        return False

    content = scroll.widget()
    assert not _inside(buttons, content)  # buttons never scroll away
    assert _inside(dialog.chars_spin, content)  # a field is inside the scroll


def test_settings_dialog_credentials_empty_by_default(qapp):
    dialog = SettingsDialog(
        AppConfig(), MockAppServices().list_audio_devices(), saved_accounts={"openai"}
    )
    # openai provider -> one credential field, empty, never prefilled
    assert "openai" in dialog._cred_edits
    assert dialog._cred_edits["openai"].text() == ""
    assert dialog.entered_credentials() == {}


def test_settings_dialog_secret_field_is_password(qapp):
    from PySide6.QtWidgets import QLineEdit

    dialog = SettingsDialog(AppConfig(), [])
    assert dialog._cred_edits["openai"].echoMode() == QLineEdit.EchoMode.Password


def test_settings_dialog_dynamic_credentials_per_provider(qapp):
    from PySide6.QtWidgets import QLineEdit

    config = AppConfig()
    config.provider = "azure-azure"
    dialog = SettingsDialog(config, [])
    # composed cloud pipeline -> one field per credential
    assert set(dialog._cred_edits) == {"azure", "azure-region"}
    assert dialog._cred_edits["azure"].echoMode() == QLineEdit.EchoMode.Password
    # region is not a secret -> normal (visible) field
    assert dialog._cred_edits["azure-region"].echoMode() == QLineEdit.EchoMode.Normal
    dialog._cred_edits["azure"].setText("az-key")
    assert dialog.entered_credentials() == {"azure": "az-key"}


def test_settings_dialog_local_model_and_device(qapp, local_visible):
    config = AppConfig()
    config.local_model = "medium"
    config.local_device = "cuda"
    dialog = SettingsDialog(config, [])
    assert dialog.local_model_combo.currentData() == "medium"
    assert dialog.local_device_combo.currentData() == "cuda"
    result = dialog.result_config()
    assert result.local_model == "medium"
    assert result.local_device == "cuda"


def test_settings_dialog_demo_provider_has_no_credentials(qapp):
    config = AppConfig()
    config.provider = "fake"
    dialog = SettingsDialog(config, [])
    assert dialog._cred_edits == {}
    assert dialog.entered_credentials() == {}


def test_settings_dialog_switching_provider_rebuilds_credentials(qapp):
    dialog = SettingsDialog(AppConfig(), [])  # openai
    assert set(dialog._cred_edits) == {"openai"}
    idx = dialog.provider_combo.findData("google-google")
    dialog.provider_combo.setCurrentIndex(idx)
    assert set(dialog._cred_edits) == {"google", "google-translate"}


def test_credential_help_label(qapp):
    from PySide6.QtGui import QPalette

    from app.gui.widgets import credential_help_label
    from app.providers.registry import (
        _CRED_AZURE_REGION,
        _CRED_OPENAI,
        CredentialField,
    )

    lbl = credential_help_label(_CRED_OPENAI)
    assert lbl is not None
    assert "platform.openai.com" in lbl.text()
    assert "<a href" in lbl.text().lower()
    assert lbl.openExternalLinks() is True  # click opens the browser, no wiring
    # readable in dark mode: muted via the placeholder-text role, not a dark
    # border tone
    pal = lbl.palette()
    assert pal.color(QPalette.ColorRole.WindowText) == pal.color(
        QPalette.ColorRole.PlaceholderText
    )
    # a credential with an instruction but no link: shown, but no anchor
    reg = credential_help_label(_CRED_AZURE_REGION)
    assert reg is not None
    assert "<a href" not in reg.text().lower()
    # a credential with no help at all: nothing to show
    assert credential_help_label(CredentialField("x", "cred.openai_key")) is None


def test_settings_credentials_show_help_link(qapp):
    from PySide6.QtWidgets import QLabel

    config = AppConfig()
    config.provider = "google-google"
    dialog = SettingsDialog(config, [])
    texts = " ".join(
        h.text() for h in dialog.findChildren(QLabel, "cred_help")
    )
    # both Google credentials link to the Google Cloud console
    assert "console.cloud.google.com" in texts
    assert "<a href" in texts.lower()


def test_settings_dialog_preserves_values_not_in_combo_lists(qapp):
    # regression: a disconnected device or a language off the list must not be
    # silently rewritten on save
    config = AppConfig()
    config.audio.device_id = 5  # not present in the mock list (0 and 1)
    config.target_language = "de"  # not present in LANGUAGES
    dialog = SettingsDialog(config, MockAppServices().list_audio_devices())
    result = dialog.result_config()
    assert result.audio.device_id == 5
    assert result.target_language == "de"


def test_apply_settings_save_failure_is_visible_and_keeps_old_config(
    qapp, tmp_path, monkeypatch
):
    # regression: a disk error during save must show a
    # message and not leave the in-memory config diverging from disk
    from PySide6.QtWidgets import QMessageBox

    window = _make_window(tmp_path)
    old_config = window._config

    def boom(_config):
        raise OSError("disk full")

    shown = {}
    monkeypatch.setattr(window._manager, "save", boom)
    monkeypatch.setattr(
        QMessageBox, "critical", staticmethod(lambda *a, **k: shown.setdefault("critical", True))
    )

    new_config = AppConfig()
    new_config.vmix.input = "NuovoTitolo"
    assert window._apply_settings(new_config, {"openai": "sk-test-key-123456789"}) is False
    assert shown.get("critical") is True
    assert window._config is old_config  # no memory/disk divergence


# ---------------------------------------------------------------- wizard


def test_wizard_collects_config(qapp):
    services = MockAppServices()
    wizard = FirstRunWizard(AppConfig(), services.list_audio_devices(), services)
    wizard.host_edit.setText("127.0.0.1")
    wizard.port_spin.setValue(8088)
    wizard.input_edit.setText("Sottopancia")

    config = wizard.result_config()
    assert config.vmix.input == "Sottopancia"
    assert config.provider == "openai"
    assert config.ui_language == "it"


def test_wizard_has_seven_pages(qapp):
    services = MockAppServices()
    wizard = FirstRunWizard(AppConfig(), services.list_audio_devices(), services)
    assert len(wizard.pageIds()) == 7


def test_wizard_credentials_page_dynamic_and_saved(qapp):
    services = MockAppServices()
    store = InMemorySecretStore()
    config = AppConfig()
    config.provider = "google-google"
    wizard = FirstRunWizard(config, services.list_audio_devices(), services, store)
    page = wizard._credentials_page
    page.initializePage()  # Qt calls this when the page is shown
    assert set(page._edits) == {"google", "google-translate"}
    page._edits["google"].setText("/creds.json")
    page._edits["google-translate"].setText("gt-key")
    assert page.validatePage() is True
    assert store.get_api_key("google") == "/creds.json"
    assert store.get_api_key("google-translate") == "gt-key"


def test_wizard_credentials_none_for_demo(qapp):
    services = MockAppServices()
    config = AppConfig()
    config.provider = "fake"
    wizard = FirstRunWizard(config, services.list_audio_devices(), services)
    page = wizard._credentials_page
    page.initializePage()
    assert page._edits == {}
    assert page.validatePage() is True  # nothing to save, still valid


def test_wizard_provider_selection_in_result(qapp):
    services = MockAppServices()
    wizard = FirstRunWizard(AppConfig(), services.list_audio_devices(), services)
    idx = wizard.provider_combo.findData("azure-azure")
    wizard.provider_combo.setCurrentIndex(idx)
    assert wizard.result_config().provider == "azure-azure"


def test_wizard_vmix_test_uses_typed_values(qapp):
    # the wizard's vMix test must use the values just typed,
    # not the starting config
    services = MockAppServices()
    wizard = FirstRunWizard(AppConfig(), services.list_audio_devices(), services)
    wizard.host_edit.setText("192.168.1.20")
    wizard.port_spin.setValue(9100)
    wizard.input_edit.setText("TitoloEvento")

    wizard._run_vmix_test()

    assert services._config is not None
    assert services._config.vmix.host == "192.168.1.20"
    assert services._config.vmix.port == 9100
    assert services._config.vmix.input == "TitoloEvento"


def test_wizard_test_button_is_async_and_shows_result(qapp):
    services = MockAppServices()
    wizard = FirstRunWizard(AppConfig(), services.list_audio_devices(), services)
    wizard.input_edit.setText("Sottopancia")

    wizard.vmix_test_button.click()
    assert _process_until(qapp, lambda: wizard.vmix_test_button.isEnabled())
    assert wizard.vmix_test_label.text().startswith("✔")


def test_wizard_test_button_survives_service_exception(qapp):
    class ExplodingServices(MockAppServices):
        def test_api(self):
            raise RuntimeError("boom")

    services = ExplodingServices()
    wizard = FirstRunWizard(AppConfig(), services.list_audio_devices(), services)
    wizard.api_test_button.click()
    assert _process_until(qapp, lambda: wizard.api_test_button.isEnabled())
    assert wizard.api_test_label.text().startswith("✘")


def test_wizard_navigation_buttons_are_italian(qapp):
    from PySide6.QtWidgets import QWizard

    services = MockAppServices()
    wizard = FirstRunWizard(AppConfig(), services.list_audio_devices(), services)
    assert "Indietro" in wizard.buttonText(QWizard.WizardButton.BackButton)
    assert "Avanti" in wizard.buttonText(QWizard.WizardButton.NextButton)
    assert wizard.buttonText(QWizard.WizardButton.FinishButton) == "Fine"
    assert wizard.buttonText(QWizard.WizardButton.CancelButton) == "Annulla"


# ---------------------------------------------------------------- subtitle overlay


def test_available_monitors_lists_screens(qapp):
    from app.gui.subtitle_overlay import available_monitors

    monitors = available_monitors()
    assert len(monitors) >= 1
    assert any(m.primary for m in monitors)


def test_subtitle_overlay_shows_and_hides_label_with_text(qapp):
    from app.gui.subtitle_overlay import SubtitleOverlay, screen_by_name

    overlay = SubtitleOverlay()
    overlay.show_on(screen_by_name(""))  # window must be shown for isVisible()
    qapp.processEvents()
    overlay.set_text("Ciao mondo")
    assert overlay._label.isVisible()
    assert overlay._label.text() == "Ciao mondo"
    overlay.set_text("   ")  # whitespace only -> hidden, no empty grey box
    assert not overlay._label.isVisible()
    overlay.close()


def test_main_window_overlay_hidden_by_default(qapp, tmp_path):
    window = _make_window(tmp_path)
    assert window._overlay is not None
    assert not window._overlay.isVisible()
    assert not window.btn_overlay.isChecked()


def test_main_window_overlay_toggle_shows_and_persists(qapp, tmp_path):
    window = _make_window(tmp_path)
    window.btn_overlay.setChecked(True)  # emits toggled -> show + save
    qapp.processEvents()
    assert window._overlay.isVisible()
    assert window._config.overlay.enabled is True
    # persisted to disk so it survives a restart
    assert window._manager.load().overlay.enabled is True
    window.close()


def test_main_window_subtitle_reaches_overlay(qapp, tmp_path):
    window = _make_window(tmp_path)
    window.btn_overlay.setChecked(True)
    qapp.processEvents()
    window.subtitle_received.emit("Testo tradotto")
    qapp.processEvents()
    assert window._overlay._label.text() == "Testo tradotto"
    assert window._overlay._label.isVisible()
    window.close()


def test_settings_dialog_overlay_roundtrip(qapp):
    config = AppConfig()
    config.overlay.enabled = True
    config.overlay.font_point_size = 48
    config.overlay.background_opacity = 200
    dialog = SettingsDialog(config, [])
    assert dialog.overlay_enabled_check.isChecked()
    assert dialog.overlay_font_spin.value() == 48
    assert dialog.overlay_opacity_spin.value() == 200

    dialog.overlay_font_spin.setValue(60)
    result = dialog.result_config()
    assert result.overlay.enabled is True
    assert result.overlay.font_point_size == 60
    assert result.overlay.background_opacity == 200


def test_overlay_label_does_not_word_wrap(qapp):
    # the overlay must honor the formatter's line count, not re-wrap by width
    from app.gui.subtitle_overlay import SubtitleOverlay

    overlay = SubtitleOverlay()
    assert overlay._label.wordWrap() is False


def test_overlay_shrinks_font_to_fit_wide_line(qapp):
    from app.gui.subtitle_overlay import SubtitleOverlay, screen_by_name

    overlay = SubtitleOverlay()
    overlay.apply_config(font_point_size=60, background_opacity=160)
    overlay.show_on(screen_by_name(""))
    qapp.processEvents()
    overlay.set_text("x" * 100)  # one very wide line
    assert overlay._current_font_size < overlay._font_point_size
    overlay.close()


def test_overlay_keeps_configured_font_for_short_text(qapp):
    from app.gui.subtitle_overlay import SubtitleOverlay, screen_by_name

    overlay = SubtitleOverlay()
    overlay.apply_config(font_point_size=18, background_opacity=160)
    overlay.show_on(screen_by_name(""))
    qapp.processEvents()
    overlay.set_text("Ciao")
    assert overlay._current_font_size == overlay._font_point_size
    overlay.close()


def test_live_screen_falls_back_to_primary_for_unknown(qapp):
    # a stale/unknown QScreen must never be used for geometry(): fall back to
    # the primary screen, which prevents the native QScreen::geometry crash
    from PySide6.QtGui import QGuiApplication

    from app.gui.subtitle_overlay import _live_screen

    primary = QGuiApplication.primaryScreen()
    assert _live_screen(None) is primary  # None -> primary
    # a live screen passes through unchanged
    assert _live_screen(primary) is primary


def test_overlay_show_on_none_screen_does_not_raise(qapp):
    from app.gui.subtitle_overlay import SubtitleOverlay

    overlay = SubtitleOverlay()
    overlay.show_on(None)  # must not touch geometry() on a missing screen
    assert overlay.isVisible()
    overlay.close()


def test_main_window_overlay_is_parentless(qapp, tmp_path):
    # decoupled from the main window so its activation/screen churn cannot drive
    # a stale-QScreen native crash
    window = _make_window(tmp_path)
    assert window._overlay is not None
    assert window._overlay.parent() is None


def test_on_screens_changed_reapplies_overlay_without_crashing(qapp, tmp_path):
    window = _make_window(tmp_path)
    window.btn_overlay.setChecked(True)  # enable + show
    qapp.processEvents()
    assert window._overlay.isVisible()
    # a simulated display-layout change must re-place the overlay, not crash
    window._on_screens_changed()
    qapp.processEvents()
    assert window._overlay.isVisible()  # still shown (enabled)
    window.close()


def test_on_screens_changed_is_noop_while_closing(qapp, tmp_path):
    window = _make_window(tmp_path)
    window._closing = True
    # must early-return without touching the overlay during teardown
    window._on_screens_changed()


def test_overlay_reasserts_topmost_on_new_text(qapp):
    # a fullscreen always-on-top app (e.g. the vMix output) shown later would
    # bury the caption: every new text must re-assert the top position
    from app.gui.subtitle_overlay import SubtitleOverlay, screen_by_name

    overlay = SubtitleOverlay()
    overlay.show_on(screen_by_name(""))
    qapp.processEvents()
    calls = []
    overlay._assert_topmost = lambda: calls.append(1)
    overlay.set_text("Ciao mondo")
    assert calls == [1]
    overlay.set_text("   ")  # cleared text must not re-raise
    assert calls == [1]
    overlay.close()


def test_overlay_raise_watchdog_follows_visibility(qapp):
    # the periodic re-assert runs only while the overlay is visible
    from app.gui.subtitle_overlay import _RAISE_INTERVAL_MS, SubtitleOverlay, screen_by_name

    overlay = SubtitleOverlay()
    assert not overlay._raise_timer.isActive()
    overlay.show_on(screen_by_name(""))
    qapp.processEvents()
    assert overlay._raise_timer.isActive()
    assert overlay._raise_timer.interval() == _RAISE_INTERVAL_MS
    overlay.hide()
    qapp.processEvents()
    assert not overlay._raise_timer.isActive()
    overlay.close()


def test_overlay_set_text_does_not_move_or_resize(qapp):
    # re-asserting z-order must never touch geometry (no flicker/jump)
    from app.gui.subtitle_overlay import SubtitleOverlay, screen_by_name

    overlay = SubtitleOverlay()
    overlay.show_on(screen_by_name(""))
    qapp.processEvents()
    before = overlay.geometry()
    overlay.set_text("Testo di prova sopra vMix")
    qapp.processEvents()
    assert overlay.geometry() == before
    overlay.close()


def test_settings_dialog_has_local_runtime_controls(qapp, local_visible):
    # download & setup of local components from the GUI (installer stays light)
    import app.local_runtime as lr

    dialog = SettingsDialog(AppConfig(), [])
    assert dialog.runtime_status_label.text() != ""
    assert dialog.btn_download_models is not None
    # the download/repair button is ALWAYS offered: a stale ".complete" marker
    # can outlive the files, and the operator must still be able to re-fetch them
    assert dialog.btn_download_runtime.isVisibleTo(dialog)
    # models can only be fetched once the components are available
    assert dialog.btn_download_models.isEnabled() == dialog._local_components_available()
    # a present marker turns the button into a repair (re-download)
    installed = lr.is_installed(device=dialog._selected_device())
    assert ("riparazione" in dialog.btn_download_runtime.text().lower()) == installed
    assert not dialog.runtime_progress.isVisibleTo(dialog)  # hidden until used


def test_settings_dialog_worker_done_restores_buttons(qapp, local_visible):
    dialog = SettingsDialog(AppConfig(), [])
    dialog.runtime_progress.setVisible(True)
    dialog.btn_download_models.setEnabled(False)
    dialog._on_worker_done(True, "fatto")
    assert not dialog.runtime_progress.isVisibleTo(dialog)
    assert dialog.runtime_status_label.text() == "fatto"


def test_wizard_local_provider_shows_runtime_controls(qapp, local_visible):
    # choosing the local provider in the wizard must offer the component/model
    # download right on the credentials page (no credentials to enter)
    config = AppConfig()
    config.provider = "local"
    wizard = FirstRunWizard(config, [], MockAppServices(), InMemorySecretStore())
    page = wizard._credentials_page
    page.initializePage()
    assert page.runtime_status_label.isVisibleTo(page)
    assert page.btn_download_models.isVisibleTo(page)
    assert page._local_hint.isVisibleTo(page)
    assert not page.runtime_progress.isVisibleTo(page)


def test_wizard_cloud_provider_hides_runtime_controls(qapp, local_visible):
    config = AppConfig()
    config.provider = "openai"
    wizard = FirstRunWizard(config, [], MockAppServices(), InMemorySecretStore())
    page = wizard._credentials_page
    page.initializePage()
    assert not page.runtime_status_label.isVisibleTo(page)
    assert not page.btn_download_models.isVisibleTo(page)
    assert not page.btn_download_runtime.isVisibleTo(page)
    assert not page._local_hint.isVisibleTo(page)


def test_wizard_result_config_carries_languages_and_model(qapp, local_visible):
    # the wizard choices drive the config AND what the model download fetches
    config = AppConfig()
    config.provider = "local"
    wizard = FirstRunWizard(config, [], MockAppServices(), InMemorySecretStore())
    _select = lambda combo, value: combo.setCurrentIndex(combo.findData(value))  # noqa: E731
    _select(wizard.source_combo, "it")
    _select(wizard.target_combo, "en")
    _select(wizard._credentials_page.local_model_combo, "medium")
    result = wizard.result_config()
    assert result.source_language == "it"
    assert result.target_language == "en"
    assert result.local_model == "medium"


def test_wizard_local_provider_shows_model_choice(qapp, local_visible):
    config = AppConfig()
    config.provider = "local"
    wizard = FirstRunWizard(config, [], MockAppServices(), InMemorySecretStore())
    page = wizard._credentials_page
    page.initializePage()
    assert page.local_model_combo.isVisibleTo(page)
    assert page.local_model_combo.currentData() == config.local_model

    # cloud provider: the model choice is hidden
    wizard.provider_combo.setCurrentIndex(wizard.provider_combo.findData("openai"))
    page.initializePage()
    assert not page.local_model_combo.isVisibleTo(page)


def test_settings_models_state_reflects_selection(qapp, local_visible, monkeypatch):
    # changing model/languages updates the hint: the next download fetches the
    # NEW selection (this was invisible before and read as "does not download")
    from app import local_runtime as lr

    dialog = SettingsDialog(AppConfig(), [])
    monkeypatch.setattr(lr, "models_cached", lambda *a, **k: False)
    dialog._refresh_models_state()
    assert "da scaricare" in dialog.runtime_status_label.text()
    monkeypatch.setattr(lr, "models_cached", lambda *a, **k: True)
    dialog._refresh_models_state()
    assert "già scaricati" in dialog.runtime_status_label.text()


def test_settings_remove_models_button_state_and_flow(qapp, local_visible, monkeypatch, tmp_path):
    # after the event the models can be removed to free disk space; the button
    # is enabled only when there is something to remove
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hub-vuota"))
    dialog = SettingsDialog(AppConfig(), [])
    assert not dialog.btn_remove_models.isEnabled()  # nothing downloaded

    # with a fake downloaded model: confirm -> removal -> freed message
    from app import local_runtime as lr

    fake = lr.DownloadedModel("Systran/faster-whisper-tiny", tmp_path, 75_000_000)
    monkeypatch.setattr(lr, "downloaded_models", lambda: [fake])
    monkeypatch.setattr(lr, "remove_downloaded_models", lambda: (75_000_000, []))
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )
    dialog._refresh_runtime_state()
    assert dialog.btn_remove_models.isEnabled()
    dialog._on_remove_models()
    assert _process_until(
        qapp, lambda: "liberato" in dialog.runtime_status_label.text().lower()
    )
    assert "75 MB" in dialog.runtime_status_label.text()


def test_download_disables_remove_button_too(qapp, local_visible, monkeypatch, tmp_path):
    # regression: removing models while a download is writing them killed the
    # download with an opaque OSError — one operation at a time
    import threading as _threading

    from app import local_runtime as lr

    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hub"))
    dialog = SettingsDialog(AppConfig(), [])
    fake = lr.DownloadedModel("Systran/faster-whisper-tiny", tmp_path, 1)
    monkeypatch.setattr(lr, "downloaded_models", lambda: [fake])
    dialog._refresh_runtime_state()
    assert dialog.btn_remove_models.isEnabled()

    release = _threading.Event()
    monkeypatch.setattr(
        lr, "download_models", lambda *a, **k: release.wait(timeout=3)
    )
    dialog._on_download_models()
    assert not dialog.btn_remove_models.isEnabled()  # blocked during download
    assert not dialog.btn_download_models.isEnabled()
    release.set()
    assert _process_until(qapp, lambda: dialog.btn_remove_models.isEnabled())


def test_settings_content_fits_without_wide_horizontal_scroll(qapp):
    # regression: a long audio-device name + the long model-state label used to
    # force the content ~1554 px wide (horizontal scrollbar on Windows 10).
    # Combos must shrink and the status label must wrap, keeping the content
    # within a normal window width.
    from PySide6.QtWidgets import QComboBox, QScrollArea

    from app.audio.devices import AudioDevice

    devices = [
        AudioDevice(
            id="x",
            name="Uscita di sistema: Speakers (Realtek(R) Audio) (loopback)",
            channels=2,
            loopback=True,
        )
    ]
    dialog = SettingsDialog(AppConfig(), devices)
    scroll = dialog.findChild(QScrollArea)
    content = scroll.widget()
    # comfortably within any real screen (was 1554 before the fix)
    assert content.minimumSizeHint().width() < 900
    # the status label wraps (its long text no longer dictates the width)
    assert dialog.runtime_status_label.wordWrap() is True
    # combos can shrink below their longest item
    for combo in content.findChildren(QComboBox):
        assert (
            combo.sizeAdjustPolicy()
            == QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )


def test_local_device_change_prompts_restart(qapp, local_visible, tmp_path, monkeypatch):
    # switching CPU<->GPU only takes effect after a restart (the pack is chosen
    # at startup): the operator must be told, not left thinking it applied
    from PySide6.QtWidgets import QMessageBox

    shown = {}
    monkeypatch.setattr(
        QMessageBox, "information", staticmethod(lambda *a, **k: shown.setdefault("info", a[2]))
    )
    window = _make_window(tmp_path)
    new_config = AppConfig()
    new_config.local_device = "cuda"  # was cpu
    assert window._apply_settings(new_config, {}) is True
    assert "riavri" in shown.get("info", "").lower() or "riapri" in shown.get("info", "").lower()

    # no prompt when the device did not change
    shown.clear()
    same = AppConfig()
    same.local_device = "cuda"
    window._config = new_config
    assert window._apply_settings(same, {}) is True
    assert "info" not in shown


# ---------------------------------------------------------------- diagnostics log


def _gui_messages(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "app.gui"]


def test_overlay_toggle_is_logged(qapp, tmp_path, caplog):
    # 18/09: whether the on-screen subtitles were on could only be guessed
    import logging

    window = _make_window(tmp_path)
    with caplog.at_level(logging.INFO, logger="app.gui"):
        window.btn_overlay.click()
        window.btn_overlay.click()
    messages = _gui_messages(caplog)
    assert any("Sottotitoli a schermo attivati" in m for m in messages)
    assert any("Sottotitoli a schermo disattivati" in m for m in messages)


def test_settings_changes_are_logged(qapp, tmp_path, caplog):
    # 18/09: the vMix port was changed to a wrong one, and the log only said
    # "Configurazione salvata"
    import logging

    window = _make_window(tmp_path)
    new_config = AppConfig()
    new_config.vmix.port = 8087
    with caplog.at_level(logging.INFO, logger="app.gui"):
        assert window._apply_settings(new_config, {}) is True
    assert any("vmix.port: 8088 → 8087" in m for m in _gui_messages(caplog))


def test_screen_changes_are_logged(qapp, tmp_path, caplog):
    import logging

    from PySide6.QtGui import QGuiApplication

    window = _make_window(tmp_path)
    screen = QGuiApplication.primaryScreen()
    with caplog.at_level(logging.INFO, logger="app.gui"):
        window._on_screen_added(screen)
        window._on_screen_removed(screen)
        window._on_primary_screen_changed(screen)
    messages = _gui_messages(caplog)
    assert any(m.startswith("Schermo collegato:") for m in messages)
    assert any(m.startswith("Schermo scollegato:") for m in messages)
    assert any(m.startswith("Schermo principale cambiato:") for m in messages)


def test_missing_overlay_monitor_is_logged(qapp, tmp_path, caplog):
    import logging

    window = _make_window(tmp_path)
    window._config.overlay.monitor = "HDbitT"  # not connected here
    window._config.overlay.enabled = True
    with caplog.at_level(logging.WARNING, logger="app.gui"):
        window._apply_overlay_state()
    assert any("HDbitT" in m and "non collegato" in m for m in _gui_messages(caplog))
    window._overlay.hide()


# ---------------------------------------------------------------- mouse wheel


def _wheel(widget, notches: int = 1):
    """Deliver a mouse-wheel event over the middle of ``widget`` (positive =
    away from the operator, i.e. scroll up / value up); returns the event."""
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent

    center = QPointF(widget.rect().center())
    event = QWheelEvent(
        center,
        widget.mapToGlobal(center),
        QPoint(0, 0),
        QPoint(0, 120 * notches),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(widget, event)
    return event


def test_wheel_changes_an_unguarded_spin_box(qapp):
    # sanity check of the harness: without the guard Qt changes the value
    from PySide6.QtWidgets import QSpinBox

    spin = QSpinBox()
    spin.setRange(1, 65535)
    spin.setValue(8088)
    event = _wheel(spin, -1)
    assert spin.value() == 8087
    assert event.isAccepted() is True  # the field consumed the wheel


def test_settings_wheel_never_changes_fields(qapp):
    # regression (live shows 10/09 and 18/09): scrolling the Settings with the
    # mouse wheel changed the vMix port under the pointer (8088 -> 8089/8087)
    from PySide6.QtCore import Qt

    dialog = SettingsDialog(_custom_config(), [])
    fields = {
        "port": dialog.port_spin,
        "chars": dialog.chars_spin,
        "lines": dialog.lines_spin,
        "interval": dialog.interval_spin,
        "clear": dialog.clear_spin,
        "provider": dialog.provider_combo,
        "local_model": dialog.local_model_combo,
        "local_device": dialog.local_device_combo,
    }
    before = {
        name: (w.value() if hasattr(w, "value") else w.currentIndex())
        for name, w in fields.items()
    }
    for widget in fields.values():
        _wheel(widget, -1)
        _wheel(widget, 3)
    after = {
        name: (w.value() if hasattr(w, "value") else w.currentIndex())
        for name, w in fields.items()
    }
    assert after == before
    assert dialog.result_config().vmix.port == 9000
    # the wheel does not even grab the focus: only a click or Tab does
    assert dialog.port_spin.focusPolicy() == Qt.FocusPolicy.StrongFocus


def test_settings_wheel_over_a_field_is_left_to_the_page(qapp):
    # the field refuses the wheel, so Qt hands the (real, OS-generated) event
    # on to the parent widgets and the scroll area scrolls the page. Qt does
    # not propagate a synthesized event, so the test checks the handoff: not
    # accepted by the field, value untouched.
    dialog = SettingsDialog(_custom_config(), [])
    event = _wheel(dialog.port_spin, -2)
    assert event.isAccepted() is False
    assert dialog.port_spin.value() == 9000


def test_wizard_wheel_never_changes_fields(qapp):
    services = MockAppServices()
    wizard = FirstRunWizard(AppConfig(), [], services)
    port = wizard.port_spin.value()
    provider = wizard.provider_combo.currentIndex()
    _wheel(wizard.port_spin, -1)
    _wheel(wizard.provider_combo, 1)
    assert wizard.port_spin.value() == port
    assert wizard.provider_combo.currentIndex() == provider


def test_saving_changed_vmix_settings_is_spelled_out(qapp, tmp_path):
    # an unnoticed vMix change must be impossible to miss after saving
    window = _make_window(tmp_path)
    new_config = AppConfig()
    new_config.vmix.port = 8087
    assert window._apply_settings(new_config, {}) is True
    message = window.statusBar().currentMessage()
    assert "Porta 8088 → 8087" in message
    assert "Test vMix" in message
    assert window.vmix_light.state == StatusState.YELLOW


def test_saving_unchanged_vmix_settings_says_saved(qapp, tmp_path):
    window = _make_window(tmp_path)
    new_config = AppConfig()
    new_config.subtitles.max_lines = 1
    assert window._apply_settings(new_config, {}) is True
    assert window.statusBar().currentMessage() == "Impostazioni salvate"


# ---------------------------------------------------------------- source language & local


def test_settings_openai_source_language_is_automatic(qapp):
    # OpenAI recognizes the spoken language by itself: asking for it misled
    # the operators, the combo shows it as automatic and is locked
    dialog = SettingsDialog(_custom_config(), [])
    assert dialog.provider_combo.currentData() == "openai"
    assert dialog.source_combo.currentData() == "auto"
    assert "automaticamente" in dialog.source_combo.currentText()
    assert not dialog.source_combo.isEnabled()
    assert dialog.result_config().source_language == "es"  # kept, not "auto"


def test_settings_other_providers_get_the_source_language_back(qapp):
    from app.gui.settings_dialog import _select_by_data

    dialog = SettingsDialog(_custom_config(), [])
    _select_by_data(dialog.provider_combo, "google-google")
    assert dialog.source_combo.isEnabled()
    assert dialog.source_combo.findData("auto") < 0  # "auto" is never savable here
    assert dialog.source_combo.currentData() == "es"
    _select_by_data(dialog.source_combo, "en")
    _select_by_data(dialog.provider_combo, "openai")
    assert dialog.source_combo.currentData() == "auto"
    assert dialog.result_config().source_language == "en"  # the last manual choice


def test_settings_hide_local_providers_by_default(qapp):
    dialog = SettingsDialog(_custom_config(), [])
    ids = [dialog.provider_combo.itemData(i) for i in range(dialog.provider_combo.count())]
    assert "local" not in ids
    assert dialog.local_box.isHidden()
    # hidden values are saved unchanged
    config = dialog.result_config()
    assert (config.local_model, config.local_device) == ("small", "cpu")


def test_settings_show_local_group_when_local_is_configured(qapp):
    # an existing local setup keeps its controls and its name in the selector
    config = _custom_config()
    config.provider = "local"
    dialog = SettingsDialog(config, [])
    assert dialog.provider_combo.currentData() == "local"
    assert dialog.provider_combo.currentText().startswith("Locale")
    assert not dialog.local_box.isHidden()


def test_settings_show_local_group_when_enabled(qapp, local_visible):
    dialog = SettingsDialog(_custom_config(), [])
    ids = [dialog.provider_combo.itemData(i) for i in range(dialog.provider_combo.count())]
    assert "local" in ids
    assert not dialog.local_box.isHidden()


def test_wizard_openai_source_language_is_automatic(qapp):
    services = MockAppServices()
    wizard = FirstRunWizard(AppConfig(), [], services)
    ids = [wizard.provider_combo.itemData(i) for i in range(wizard.provider_combo.count())]
    assert "local" not in ids
    assert wizard.provider_combo.currentData() == "openai"
    assert wizard.source_combo.currentData() == "auto"
    assert not wizard.source_combo.isEnabled()
    assert wizard.result_config().source_language == "es"


def test_diagnostics_show_automatic_source_language_for_openai(qapp, tmp_path):
    window = _make_window(tmp_path)
    assert "Lingue: rilevata automaticamente → it" in window.diagnostics_text()

