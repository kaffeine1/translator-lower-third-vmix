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
    window = _make_window(tmp_path)
    assert window.btn_start.isEnabled()
    assert not window.btn_stop.isEnabled()
    window.btn_start.click()
    assert not window.btn_start.isEnabled()
    assert window.btn_stop.isEnabled()
    window.btn_stop.click()
    assert window.btn_start.isEnabled()
    assert not window.btn_stop.isEnabled()


def test_start_updates_subtitle_preview(qapp, tmp_path):
    window = _make_window(tmp_path)
    window.btn_start.click()
    qapp.processEvents()
    assert "demo" in window.preview.text()


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
    # live errors end up in the status bar and in the vMix status light,
    # without modal dialogs that would interrupt the event
    window = _make_window(tmp_path)
    window.audio_light.set_state(StatusState.GREEN)
    window._services._emit_error("vMix non raggiungibile")
    qapp.processEvents()
    assert window.vmix_light.state == StatusState.RED
    assert "vmix non raggiungibile" in window.statusBar().currentMessage().lower()


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
    assert services.running is True


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
    assert dialog.source_combo.currentData() == "es"
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
    config.provider = "azure-deepl"
    dialog = SettingsDialog(config, [])
    # composed cloud pipeline -> one field per credential
    assert set(dialog._cred_edits) == {"azure", "azure-region", "deepl"}
    assert dialog._cred_edits["azure"].echoMode() == QLineEdit.EchoMode.Password
    # region is not a secret -> normal (visible) field
    assert dialog._cred_edits["azure-region"].echoMode() == QLineEdit.EchoMode.Normal
    dialog._cred_edits["deepl"].setText("dk:fx")
    assert dialog.entered_credentials() == {"deepl": "dk:fx"}


def test_settings_dialog_local_model_and_device(qapp):
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
    idx = dialog.provider_combo.findData("google-deepl")
    dialog.provider_combo.setCurrentIndex(idx)
    assert set(dialog._cred_edits) == {"google", "deepl"}


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
    config.provider = "google-deepl"
    wizard = FirstRunWizard(config, services.list_audio_devices(), services, store)
    page = wizard._credentials_page
    page.initializePage()  # Qt calls this when the page is shown
    assert set(page._edits) == {"google", "deepl"}
    page._edits["google"].setText("/creds.json")
    page._edits["deepl"].setText("dk:fx")
    assert page.validatePage() is True
    assert store.get_api_key("google") == "/creds.json"
    assert store.get_api_key("deepl") == "dk:fx"


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
    idx = wizard.provider_combo.findData("azure-deepl")
    wizard.provider_combo.setCurrentIndex(idx)
    assert wizard.result_config().provider == "azure-deepl"


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


def test_settings_dialog_has_local_runtime_controls(qapp):
    # download & setup of local components from the GUI (installer stays light)
    dialog = SettingsDialog(AppConfig(), [])
    assert dialog.runtime_status_label.text() != ""
    assert dialog.btn_download_models is not None
    # in the dev environment the packages are importable -> download hidden,
    # models button enabled; without them the inverse must hold
    if dialog._local_components_available():
        assert not dialog.btn_download_runtime.isVisibleTo(dialog)
        assert dialog.btn_download_models.isEnabled()
    else:
        assert dialog.btn_download_runtime.isVisibleTo(dialog)
        assert not dialog.btn_download_models.isEnabled()
    assert not dialog.runtime_progress.isVisibleTo(dialog)  # hidden until used


def test_settings_dialog_worker_done_restores_buttons(qapp):
    dialog = SettingsDialog(AppConfig(), [])
    dialog.runtime_progress.setVisible(True)
    dialog.btn_download_models.setEnabled(False)
    dialog._on_worker_done(True, "fatto")
    assert not dialog.runtime_progress.isVisibleTo(dialog)
    assert dialog.runtime_status_label.text() == "fatto"


def test_wizard_local_provider_shows_runtime_controls(qapp):
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


def test_wizard_cloud_provider_hides_runtime_controls(qapp):
    config = AppConfig()
    config.provider = "openai"
    wizard = FirstRunWizard(config, [], MockAppServices(), InMemorySecretStore())
    page = wizard._credentials_page
    page.initializePage()
    assert not page.runtime_status_label.isVisibleTo(page)
    assert not page.btn_download_models.isVisibleTo(page)
    assert not page.btn_download_runtime.isVisibleTo(page)
    assert not page._local_hint.isVisibleTo(page)
