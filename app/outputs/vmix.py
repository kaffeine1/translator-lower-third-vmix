# Translator Lower Third for vMix
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""VmixOutput — vMix HTTP API client.

Endpoint:
    http://HOST:PORT/api/?Function=SetText&Input=INPUT&SelectedName=FIELD&Value=TEXT

Parameters are always encoded by the HTTP client (never string
concatenation). Short timeouts and a single retry on transport errors: during
a live show it is better to drop an update than to queue slow requests.
Calls are blocking: GUI callers must run them off the Qt thread
(see MainWindow._call_service_async).
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

import httpx

logger = logging.getLogger("app.outputs.vmix")

DEFAULT_TIMEOUT_S = 2.0
ATTEMPTS = 2  # 1 attempt + 1 light retry on transport errors

TEST_PHRASE = "Test sottopancia"


class VmixError(Exception):
    """vMix error with an operator-readable message (in Italian)."""


class VmixOutput:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8088,
        input: str = "",
        selected_name: str = "Headline.Text",
        timeout_s: float = DEFAULT_TIMEOUT_S,
        client: httpx.Client | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.input = input
        self.selected_name = selected_name
        self._base_url = f"http://{host}:{port}/api/"
        self._client = client or httpx.Client(timeout=timeout_s)

    # ------------------------------------------------------------------ API

    def test_connection(self) -> str:
        """Check that /api responds; return the vMix version if readable."""
        response = self._get({})
        try:
            root = ET.fromstring(response.text)
            return root.findtext("version", default="")
        except ET.ParseError:
            # reachable but unexpected XML: the connection is still valid
            return ""

    def set_text(self, text: str) -> None:
        if not self.input:
            raise VmixError(
                "Nessun titolo vMix configurato: imposta il campo "
                "Input/Titolo nelle Impostazioni."
            )
        self._get(
            {
                "Function": "SetText",
                "Input": self.input,
                "SelectedName": self.selected_name,
                "Value": text,
            }
        )

    def clear_text(self) -> None:
        self.set_text("")

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> VmixOutput:
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # ------------------------------------------------------------------ HTTP

    def _get(self, params: dict) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(1, ATTEMPTS + 1):
            try:
                response = self._client.get(self._base_url, params=params)
            except httpx.TransportError as exc:
                last_exc = exc
                logger.warning(
                    "vMix %s:%s non raggiungibile (tentativo %s/%s): %s",
                    self.host,
                    self.port,
                    attempt,
                    ATTEMPTS,
                    type(exc).__name__,
                )
                continue
            if response.status_code != 200:
                # vMix explains the error in the body ("Invalid input name…"):
                # it goes to the logs or the Open Log button adds nothing
                logger.warning(
                    "vMix ha risposto HTTP %s a %s: %s",
                    response.status_code,
                    params.get("Function", "stato"),
                    response.text[:200].strip(),
                )
                raise VmixError(self._http_error_message(response.status_code, params))
            return response
        raise VmixError(
            f"vMix non raggiungibile su {self.host}:{self.port}. "
            "Controlla che vMix sia aperto e che il Web Controller sia attivo."
        ) from last_exc

    @staticmethod
    def _http_error_message(status_code: int, params: dict) -> str:
        if status_code in (401, 403):
            return (
                f"vMix richiede una password per il Web Controller (HTTP {status_code}). "
                "Controlla le impostazioni Web Controller in vMix."
            )
        if params.get("Function") == "SetText":
            return (
                f"vMix ha risposto con un errore (HTTP {status_code}). "
                "Controlla il nome del titolo e del campo di testo."
            )
        return (
            f"vMix ha risposto con un errore (HTTP {status_code}). "
            "Controlla host, porta e impostazioni del Web Controller."
        )
