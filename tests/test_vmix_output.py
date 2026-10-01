# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""VmixOutput tests (Milestone 4) — httpx.MockTransport, no real network."""

from __future__ import annotations

import httpx
import pytest

from app.config.models import AppConfig
from app.outputs.vmix import ATTEMPTS, TEST_PHRASE, VmixError, VmixOutput
from app.services import LiveAppServices


def _vmix_with_handler(handler, **kwargs) -> VmixOutput:
    client = httpx.Client(transport=httpx.MockTransport(handler), timeout=1.0)
    kwargs.setdefault("input", "Sottopancia")
    return VmixOutput(client=client, **kwargs)


# ---------------------------------------------------------------- SetText URL


def test_settext_url_parameters():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text="Function completed successfully.")

    vmix = _vmix_with_handler(handler, host="127.0.0.1", port=8088)
    vmix.set_text("Ciao mondo")

    request = seen[0]
    assert request.url.host == "127.0.0.1"
    assert request.url.port == 8088
    assert request.url.path == "/api/"
    params = request.url.params
    assert params["Function"] == "SetText"
    assert params["Input"] == "Sottopancia"
    assert params["SelectedName"] == "Headline.Text"
    assert params["Value"] == "Ciao mondo"


def test_special_characters_are_encoded_and_roundtrip():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    text = 'È già qui: ¿qué pasa? & <b>"ciao"</b> 100%'
    vmix = _vmix_with_handler(handler)
    vmix.set_text(text)

    raw_url = str(seen[0].url)
    # no dangerous unencoded character in the query
    query = raw_url.split("?", 1)[1]
    assert "<" not in query and '"' not in query
    # the decoded value must come back identical to the original
    assert seen[0].url.params["Value"] == text


def test_custom_field_and_input_names():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    vmix = _vmix_with_handler(handler, input="7", selected_name="Titolo.Text")
    vmix.set_text("x")
    assert seen[0].url.params["Input"] == "7"
    assert seen[0].url.params["SelectedName"] == "Titolo.Text"


def test_set_text_without_input_raises_operator_error():
    vmix = _vmix_with_handler(lambda request: httpx.Response(200), input="")
    with pytest.raises(VmixError) as excinfo:
        vmix.set_text("ciao")
    assert "Impostazioni" in str(excinfo.value)


def test_clear_text_sends_empty_value():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    vmix = _vmix_with_handler(handler)
    vmix.clear_text()
    assert seen[0].url.params["Value"] == ""


# ---------------------------------------------------------------- errors


def test_timeout_retries_then_raises_readable_error():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        raise httpx.ConnectTimeout("timeout")

    vmix = _vmix_with_handler(handler, host="10.0.0.9", port=9999)
    with pytest.raises(VmixError) as excinfo:
        vmix.set_text("ciao")
    assert calls["count"] == ATTEMPTS  # one light retry, then error
    message = str(excinfo.value)
    assert "10.0.0.9:9999" in message
    assert "vMix" in message


def test_connection_refused_raises_readable_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    vmix = _vmix_with_handler(handler)
    with pytest.raises(VmixError) as excinfo:
        vmix.test_connection()
    assert "Web Controller" in str(excinfo.value)


def test_transient_error_recovered_by_retry():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            raise httpx.ReadTimeout("slow")
        return httpx.Response(200)

    vmix = _vmix_with_handler(handler)
    vmix.set_text("ciao")  # must not raise
    assert calls["count"] == 2


def test_non_200_response_raises_without_retry():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(500, text="Invalid input name")

    vmix = _vmix_with_handler(handler)
    with pytest.raises(VmixError) as excinfo:
        vmix.set_text("ciao")
    assert calls["count"] == 1  # the server responded: no retry
    assert "HTTP 500" in str(excinfo.value)


def test_auth_error_message_points_to_web_controller():
    vmix = _vmix_with_handler(lambda request: httpx.Response(401, text="Unauthorized"))
    with pytest.raises(VmixError) as excinfo:
        vmix.test_connection()
    message = str(excinfo.value)
    assert "password" in message.lower()
    assert "titolo" not in message.lower()  # do not blame the title name


def test_default_client_uses_short_timeout():
    from app.outputs.vmix import DEFAULT_TIMEOUT_S

    vmix = VmixOutput()
    try:
        assert vmix._client.timeout == httpx.Timeout(DEFAULT_TIMEOUT_S)
    finally:
        vmix.close()


# ---------------------------------------------------------------- connection


def test_connection_parses_vmix_version():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text="<vmix><version>27.0.0.49</version><edition>4K</edition></vmix>"
        )

    vmix = _vmix_with_handler(handler)
    assert vmix.test_connection() == "27.0.0.49"


def test_connection_with_unexpected_body_still_succeeds():
    vmix = _vmix_with_handler(lambda request: httpx.Response(200, text="not xml"))
    assert vmix.test_connection() == ""


# ---------------------------------------------------------------- services


def _configured_services(monkeypatch, handler, vmix_input="Sottopancia"):
    from app.audio.input import FakeAudioInput

    services = LiveAppServices(FakeAudioInput())
    config = AppConfig()
    config.vmix.input = vmix_input
    services.update_config(config)

    client = httpx.Client(transport=httpx.MockTransport(handler), timeout=1.0)
    original_init = VmixOutput.__init__

    def patched_init(self, **kwargs):
        kwargs["client"] = client
        original_init(self, **kwargs)

    monkeypatch.setattr(VmixOutput, "__init__", patched_init)
    return services


def test_service_test_vmix_sends_test_phrase(monkeypatch):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text="<vmix><version>27</version></vmix>")

    services = _configured_services(monkeypatch, handler)
    result = services.test_vmix()
    assert result.ok is True
    assert "Sottopancia" in result.message
    set_text_calls = [r for r in seen if r.url.params.get("Function") == "SetText"]
    assert len(set_text_calls) == 1
    assert set_text_calls[0].url.params["Value"] == TEST_PHRASE


def test_service_test_vmix_without_input_warns_operator(monkeypatch):
    services = _configured_services(
        monkeypatch, lambda request: httpx.Response(200), vmix_input=""
    )
    result = services.test_vmix()
    assert result.ok is False
    assert "titolo" in result.message.lower()


def test_service_test_vmix_unreachable_is_readable(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    services = _configured_services(monkeypatch, handler)
    result = services.test_vmix()
    assert result.ok is False
    assert "vMix" in result.message


# ---------------------------------------------------------------- failure logging


def test_failure_streak_logs_detail_once_then_periodic_summary(caplog, monkeypatch):
    # regression (live show 18/09): an unreachable vMix wrote 22,852 identical
    # warnings in one day, flooding the logs; now: detail at the start of the
    # streak, then one summary line per interval
    import logging

    import app.outputs.vmix as mod

    clock = {"t": 1000.0}
    monkeypatch.setattr(mod.time, "monotonic", lambda: clock["t"])

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout")

    vmix = _vmix_with_handler(handler)
    with caplog.at_level(logging.INFO, logger="app.outputs.vmix"):
        for _ in range(10):
            with pytest.raises(VmixError):
                vmix.set_text("x")
            clock["t"] += 4.0
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warnings) == ATTEMPTS  # only the first request, per attempt

        clock["t"] += mod.FAILURE_SUMMARY_INTERVAL_S
        with pytest.raises(VmixError):
            vmix.set_text("x")
    summaries = [r.getMessage() for r in caplog.records if "ancora in errore" in r.getMessage()]
    assert summaries == ["vMix 127.0.0.1:8088 ancora in errore: 11 invii falliti di fila"]


def test_recovery_after_failures_is_logged(caplog):
    import logging

    state = {"down": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["down"]:
            raise httpx.ConnectError("refused")
        return httpx.Response(200)

    vmix = _vmix_with_handler(handler)
    with caplog.at_level(logging.INFO, logger="app.outputs.vmix"):
        for _ in range(3):
            with pytest.raises(VmixError):
                vmix.set_text("x")
        state["down"] = False
        vmix.set_text("x")
    assert any(
        "di nuovo raggiungibile dopo 3 invii falliti" in r.getMessage() for r in caplog.records
    )


# ---------------------------------------------------------------- live session


def test_session_reports_vmix_failure_once_then_recovery(caplog):
    import logging

    from app.services import STATUS_VMIX, _VmixPublisher

    state = {"down": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["down"]:
            raise httpx.ConnectError("refused")
        return httpx.Response(200)

    errors, statuses = [], []
    publisher = _VmixPublisher(
        _vmix_with_handler(handler),
        errors.append,
        lambda channel, ok, message: statuses.append((channel, ok)),
    )
    publisher.publish("uno")
    publisher.publish("due")
    assert len(errors) == 1  # told once, not on every subtitle
    assert statuses == [(STATUS_VMIX, False)]
    assert publisher.failing is True

    state["down"] = False
    with caplog.at_level(logging.INFO, logger="app.services"):
        publisher.publish("tre")
        publisher.publish("quattro")
    assert statuses == [(STATUS_VMIX, False), (STATUS_VMIX, True)]  # light back to green
    assert publisher.failing is False
    firsts = [r for r in caplog.records if "primo invio riuscito" in r.getMessage()]
    assert len(firsts) == 1  # the session's first delivery is on record, once


def test_session_first_delivery_turns_vmix_light_green():
    from app.services import STATUS_VMIX, _VmixPublisher

    statuses = []
    publisher = _VmixPublisher(
        _vmix_with_handler(lambda request: httpx.Response(200)),
        lambda message: None,
        lambda channel, ok, message: statuses.append((channel, ok)),
    )
    publisher.publish("uno")
    publisher.publish("due")
    assert statuses == [(STATUS_VMIX, True)]


def test_stop_skips_clearing_an_unreachable_vmix(monkeypatch):
    # an unreachable vMix used to add two more timeouts to every STOP
    from app.services import _VmixPublisher

    values: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        values.append(request.url.params.get("Value"))
        raise httpx.ConnectError("refused")

    services = _configured_services(monkeypatch, handler)
    services._vmix = VmixOutput(input="Sottopancia")
    services._publisher = _VmixPublisher(
        services._vmix, lambda message: None, lambda channel, ok, message: None
    )
    services._publisher.publish("ciao")  # fails: vMix unreachable
    values.clear()
    services.stop_translation()
    assert values == []  # no clear attempt
    assert services._vmix is None


def test_stop_clears_the_title_when_vmix_answers(monkeypatch):
    from app.services import _VmixPublisher

    values: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        values.append(request.url.params.get("Value"))
        return httpx.Response(200)

    services = _configured_services(monkeypatch, handler)
    services._vmix = VmixOutput(input="Sottopancia")
    services._publisher = _VmixPublisher(
        services._vmix, lambda message: None, lambda channel, ok, message: None
    )
    services._publisher.publish("ciao")
    services.stop_translation()
    assert values == ["ciao", ""]  # the title is cleared at the end of the show


def test_session_with_invalid_vmix_address_reports_once():
    # e.g. the port pasted into the Host field: no traceback per subtitle, one
    # readable message and a red vMix light
    from app.services import STATUS_VMIX, _VmixPublisher

    errors, statuses = [], []
    vmix = VmixOutput(host="127.0.0.1:8088", port=8088, input="Sottopancia")
    try:
        publisher = _VmixPublisher(
            vmix, errors.append, lambda channel, ok, message: statuses.append((channel, ok))
        )
        publisher.publish("uno")
        publisher.publish("due")
    finally:
        vmix.close()
    assert len(errors) == 1
    assert "127.0.0.1:8088" in errors[0]
    assert statuses == [(STATUS_VMIX, False)]
