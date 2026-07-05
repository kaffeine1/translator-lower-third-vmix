# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""i18n tests: catalog lookup, formatting, fallback, locale switching."""

from __future__ import annotations

import app.i18n as i18n
from app.config.models import AppConfig
from app.i18n import available_locales, get_locale, set_locale, t


def test_default_locale_is_italian():
    assert i18n.DEFAULT_LOCALE == "it"
    assert get_locale() == "it"


def test_t_returns_italian_string():
    assert t("service.translation_started") == "Traduzione avviata"
    assert t("widgets.status.ok") == "OK"


def test_t_formats_named_placeholders():
    msg = t("vmix.unreachable", host="10.0.0.5", port=9000)
    assert "10.0.0.5:9000" in msg
    assert msg.startswith("vMix non raggiungibile su 10.0.0.5:9000")


def test_t_unknown_key_returns_key():
    assert t("chiave.inesistente") == "chiave.inesistente"


def test_t_missing_placeholder_does_not_crash():
    # kwargs assenti: ritorna il testo grezzo senza sollevare
    out = t("vmix.unreachable")
    assert "{host}" in out  # non formattato, ma nessuna eccezione


def test_available_locales_has_italian():
    locales = available_locales()
    assert locales["it"] == "Italiano"


def test_set_locale_unknown_falls_back_to_default():
    set_locale("de")  # non presente
    assert get_locale() == "it"
    set_locale("it")


def test_all_catalog_values_are_strings():
    for key, value in i18n.CATALOGS["it"].items():
        assert isinstance(value, str), key


def test_config_ui_language_roundtrips():
    config = AppConfig.from_dict({"ui_language": "en"})
    assert config.ui_language == "en"
    assert "ui_language" in config.to_dict()


def test_config_ui_language_defaults_to_italian():
    assert AppConfig().ui_language == "it"
    assert AppConfig.from_dict({}).ui_language == "it"
