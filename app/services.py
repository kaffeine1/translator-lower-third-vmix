# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""Service layer between the GUI and the pipeline.

The GUI depends only on the AppServices interface. Milestone 2 wires
MockAppServices (canned responses, no I/O); later milestones plug real
audio/provider/vMix implementations behind the same interface without
touching GUI code.
"""

from __future__ import annotations

import abc
import logging
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from app.audio.devices import AudioDevice, AudioInputError
from app.audio.input import AudioInput
from app.audio.levels import rms_level
from app.config.models import AppConfig
from app.config.secrets import SecretStorageError, SecretStore
from app.i18n import t
from app.outputs.vmix import TEST_PHRASE, VmixError, VmixOutput
from app.providers.base import ProviderError

logger = logging.getLogger("app.services")

SubtitleCallback = Callable[[str], None]
LevelCallback = Callable[[float], None]
# (channel, ok, operator message or ""): drives the API/vMix status lights
StatusCallback = Callable[[str, bool, str], None]

# status channels reported during a translation
STATUS_API = "api"
STATUS_VMIX = "vmix"


@dataclass
class ServiceResult:
    ok: bool
    message: str  # operator-readable, Italian


class AppServices(abc.ABC):
    """Pipeline operations the GUI can trigger.

    From Milestone 3 onward implementations do real I/O and must never block
    the GUI thread. The subtitle listener may be invoked from worker threads:
    GUI consumers must marshal it onto the Qt thread (signal emit).
    """

    def __init__(self) -> None:
        self._subtitle_listener: SubtitleCallback | None = None
        self._error_listener: SubtitleCallback | None = None
        self._status_listener: StatusCallback | None = None
        self._config: AppConfig | None = None
        # True while a translation is running (read by the GUI after START/STOP)
        self.running = False

    def update_config(self, config: AppConfig) -> None:
        """Current configuration: the GUI updates it on every change."""
        self._config = config

    def set_subtitle_listener(self, callback: SubtitleCallback | None) -> None:
        self._subtitle_listener = callback

    def set_error_listener(self, callback: SubtitleCallback | None) -> None:
        """Pipeline errors during translation (e.g. vMix down, provider
        disconnected). May arrive from worker threads: marshal onto the Qt thread."""
        self._error_listener = callback

    def set_status_listener(self, callback: StatusCallback | None) -> None:
        """Health of the provider (STATUS_API) and of vMix (STATUS_VMIX) during
        a translation: ok=False when it starts failing, ok=True when it works
        (again), with an optional operator message. May arrive from worker
        threads: marshal onto the Qt thread."""
        self._status_listener = callback

    def _emit_status(self, channel: str, ok: bool, message: str = "") -> None:
        if self._status_listener is not None:
            self._status_listener(channel, ok, message)

    def _emit_subtitle(self, text: str) -> None:
        if self._subtitle_listener is not None:
            self._subtitle_listener(text)

    def _emit_error(self, message: str) -> None:
        if self._error_listener is not None:
            self._error_listener(message)

    @abc.abstractmethod
    def list_audio_devices(self) -> list[AudioDevice]: ...

    @abc.abstractmethod
    def start_audio_monitor(
        self, device_id: int | str | None, on_level: LevelCallback
    ) -> ServiceResult:
        """Start listening for the Audio Test; on_level receives levels 0.0–1.0.

        on_level may arrive from an audio thread: GUI consumers must marshal it
        back onto the Qt thread (signal emit).
        """

    @abc.abstractmethod
    def stop_audio_monitor(self) -> None: ...

    @abc.abstractmethod
    def test_api(self) -> ServiceResult: ...

    @abc.abstractmethod
    def test_vmix(self) -> ServiceResult: ...

    @abc.abstractmethod
    def start_translation(self) -> ServiceResult: ...

    @abc.abstractmethod
    def stop_translation(self) -> ServiceResult: ...


class _VmixPublisher:
    """Sends the subtitles of one translation session to vMix.

    Tracks whether vMix is answering, so the operator is told once when it
    starts failing (not on every subtitle) and sees the vMix light turn green
    again when it recovers; the log records the session's first successful
    send, because a success is otherwise silent and a live-show post-mortem
    could not tell whether vMix ever received anything."""

    def __init__(
        self,
        vmix: VmixOutput,
        on_error: SubtitleCallback,
        on_status: StatusCallback,
    ) -> None:
        self.vmix = vmix
        self._on_error = on_error
        self._on_status = on_status
        self._delivered = False
        self.failing = False

    def publish(self, text: str) -> None:
        try:
            self.vmix.set_text(text)
        except VmixError as exc:
            self._fail(str(exc))
            return
        except (httpx.HTTPError, httpx.InvalidURL, ValueError) as exc:
            # e.g. port pasted into the Host field: an invalid URL, which
            # would otherwise log a traceback for every subtitle
            logger.debug("Indirizzo vMix non valido: %s", type(exc).__name__)
            self._fail(
                t("service.vmix_invalid_address", host=self.vmix.host, port=self.vmix.port)
            )
            return
        first = not self._delivered
        recovered = self.failing
        self._delivered = True
        self.failing = False
        if first:
            logger.info(
                "vMix raggiungibile: primo invio riuscito a %s:%s (input '%s', campo '%s')",
                self.vmix.host,
                self.vmix.port,
                self.vmix.input,
                self.vmix.selected_name,
            )
        if first or recovered:
            self._on_status(STATUS_VMIX, True, "")

    def _fail(self, message: str) -> None:
        if not self.failing:
            self.failing = True
            self._on_error(message)
            self._on_status(STATUS_VMIX, False, "")


class MockAppServices(AppServices):
    """Canned responses for GUI development and tests. No real I/O.

    Set the fail_* flags to exercise the error paths.
    """

    def __init__(self) -> None:
        super().__init__()
        self.fail_audio = False
        self.fail_api = False
        self.fail_vmix = False
        self.running = False
        self.monitoring = False
        self.mock_levels: tuple[float, ...] = (0.4, 0.7, 0.6)

    def list_audio_devices(self) -> list[AudioDevice]:
        return [
            AudioDevice(id=0, name="Microfono (demo)", channels=1, default=True),
            AudioDevice(id=1, name="Mixer USB (demo)", channels=2),
        ]

    def start_audio_monitor(
        self, device_id: int | str | None, on_level: LevelCallback
    ) -> ServiceResult:
        if self.fail_audio:
            return ServiceResult(False, t("service.audio_open_failed"))
        self.monitoring = True
        for level in self.mock_levels:
            on_level(level)
        return ServiceResult(True, t("service.audio_listening"))

    def stop_audio_monitor(self) -> None:
        self.monitoring = False

    def test_api(self) -> ServiceResult:
        if self.fail_api:
            return ServiceResult(False, t("service.api_key_invalid"))
        return ServiceResult(True, t("service.api_connection_ok_demo"))

    def test_vmix(self) -> ServiceResult:
        if self.fail_vmix:
            return ServiceResult(False, t("service.vmix_unreachable"))
        return ServiceResult(True, t("service.vmix_test_sent_demo"))

    def start_translation(self) -> ServiceResult:
        self.running = True
        self._emit_subtitle(t("service.demo_subtitle"))
        return ServiceResult(True, t("service.translation_started_demo"))

    def stop_translation(self) -> ServiceResult:
        self.running = False
        return ServiceResult(True, t("service.translation_stopped"))


class LiveAppServices(MockAppServices):
    """Progressively real services: real audio (M3) and vMix (M4), translation
    provider still mocked until Milestone 7.

    The GUI does not change because it depends only on the AppServices interface.
    """

    def __init__(self, audio_input: AudioInput, secret_store: SecretStore | None = None) -> None:
        super().__init__()
        self._audio = audio_input
        self._secret_store = secret_store
        self._pipeline = None
        self._vmix: VmixOutput | None = None
        self._publisher: _VmixPublisher | None = None
        # set by a provider error, cleared when translation flows again
        self._api_failed = False

    def update_config(self, config: AppConfig) -> None:
        super().update_config(config)
        # subtitle formatting is applied live: changing lines/chars/timings
        # updates a running translation without a stop/start. Provider, audio
        # and vMix changes still take effect on the next START.
        if self._pipeline is not None:
            self._pipeline.update_subtitle_config(config.subtitles)

    def _make_provider(self):
        """Translation provider in use, chosen from the registry based on
        config.provider. If the provider requires an API key but none is
        saved, fall back to the demo (fake) so the GUI stays usable."""
        from app.providers.registry import (
            DEFAULT_PROVIDER_ID,
            create_provider,
            get_provider_info,
        )

        provider_id = self._config.provider if self._config else DEFAULT_PROVIDER_ID
        info = get_provider_info(provider_id)
        if info is None:
            logger.warning("Provider '%s' sconosciuto: uso la demo", provider_id)
            return create_provider("fake", self._secret_store)
        missing = [name for name in info.required_key_names if not self._has_key(name)]
        if missing:
            # log only the NAMES of the missing accounts, never the values
            logger.info(
                "Chiavi mancanti per '%s' (%s): uso il provider demo",
                provider_id,
                ", ".join(missing),
            )
            return create_provider("fake", self._secret_store)
        return create_provider(provider_id, self._secret_store, self._config)

    def _has_key(self, provider_id: str) -> bool:
        if self._secret_store is None:
            return False
        try:
            return bool(self._secret_store.get_api_key(provider_id))
        except SecretStorageError:
            return False

    def test_api(self) -> ServiceResult:
        if self._config is None:
            return ServiceResult(False, t("service.config_unavailable"))
        from app.providers.registry import get_provider_info

        provider_id = self._config.provider
        info = get_provider_info(provider_id)
        if provider_id == "local":
            # no credentials, but it needs the optional heavy packages installed;
            # report honestly instead of a false "demo ok"
            return self._probe_local_packages()
        if info is None or not info.requires_api_key:
            return ServiceResult(True, t("service.demo_mode_no_key"))
        if self._secret_store is None:
            return ServiceResult(False, t("service.config_unavailable"))
        # every credential the provider needs must be present
        missing = [name for name in info.required_key_names if not self._has_key(name)]
        if missing:
            return ServiceResult(False, t("service.no_api_key_saved"))
        if provider_id == "openai":
            import asyncio

            from app.providers.openai_realtime import OpenAIProviderError, check_api_key

            try:
                asyncio.run(check_api_key(self._secret_store, "openai"))
            except OpenAIProviderError as exc:
                return ServiceResult(False, str(exc))
            except Exception:
                logger.exception("Verifica API fallita")
                return ServiceResult(False, t("service.api_verify_failed"))
            return ServiceResult(True, t("service.api_connection_ok"))
        # composed cloud providers: no live check available (would need the SDKs)
        return ServiceResult(True, t("service.credentials_present"))

    @staticmethod
    def _probe_local_packages() -> ServiceResult:
        """Check that the optional local-provider packages are importable.

        The local pipeline needs no credentials, so without this check test_api
        would report a misleading "demo ok". We only probe for the packages
        (find_spec, no import) — the heavy models are fetched at first START.
        """
        import importlib.util

        missing = [
            name
            for name in ("faster_whisper", "transformers")
            if importlib.util.find_spec(name) is None
        ]
        if missing:
            return ServiceResult(False, t("service.local_packages_missing"))
        return ServiceResult(True, t("service.local_ready"))

    def start_translation(self) -> ServiceResult:
        if self._config is None:
            return ServiceResult(False, t("service.config_unavailable"))
        if self._pipeline is not None:
            return ServiceResult(True, t("service.translation_already_started"))

        from app.pipeline import TranslationPipeline

        vmix_config = self._config.vmix
        vmix = VmixOutput(
            host=vmix_config.host,
            port=vmix_config.port,
            input=vmix_config.input,
            selected_name=vmix_config.selected_name,
        )
        publisher = _VmixPublisher(vmix, self._emit_error, self._emit_status)
        self._api_failed = False

        pipeline = TranslationPipeline(
            self._make_provider(),
            self._config,
            on_subtitle=self._on_pipeline_subtitle,
            output_publish=publisher.publish,
            on_error=self._on_provider_error,
            audio_input=self._audio,
            on_recovered=self._on_provider_recovered,
        )
        try:
            pipeline.start()
        except ProviderError as exc:
            # readable provider error (e.g. missing key/package): show it to the
            # operator instead of the generic "consult the logs" message
            logger.warning("Avvio provider fallito: %s", type(exc).__name__)
            vmix.close()
            return ServiceResult(False, str(exc))
        except TimeoutError:
            # the provider did not answer the connection in time (slow or
            # missing Internet): say so instead of "consult the logs"
            logger.warning("Avvio provider scaduto: nessuna risposta dal servizio")
            vmix.close()
            return ServiceResult(False, t("service.provider_timeout"))
        except Exception:
            logger.exception("Avvio pipeline fallito")
            vmix.close()
            return ServiceResult(
                False, t("service.translation_start_failed")
            )
        self._pipeline = pipeline
        self._vmix = vmix
        self._publisher = publisher
        self.running = True
        return ServiceResult(True, t("service.translation_started"))

    def _on_provider_error(self, message: str) -> None:
        self._api_failed = True
        self._emit_error(message)
        self._emit_status(STATUS_API, False)

    def _on_provider_recovered(self) -> None:
        self._api_failed = False
        self._emit_status(STATUS_API, True, t("provider.connection_restored"))

    def _on_pipeline_subtitle(self, text: str) -> None:
        if text and self._api_failed:
            # translated text is flowing again: the provider has recovered
            self._api_failed = False
            self._emit_status(STATUS_API, True)
        self._emit_subtitle(text)

    def stop_translation(self) -> ServiceResult:
        if self._pipeline is not None:
            self._pipeline.stop()
            self._pipeline = None
        if self._vmix is not None:
            if self._publisher is not None and self._publisher.failing:
                # vMix is not answering: clearing the title would only add
                # two more timeouts to the STOP
                logger.info("vMix non raggiungibile: salto la pulizia del titolo")
            else:
                try:
                    self._vmix.clear_text()  # clear the title at the end of the live show
                except VmixError:
                    pass
            self._vmix.close()
            self._vmix = None
        self._publisher = None
        self.running = False
        return ServiceResult(True, t("service.translation_stopped"))

    def test_vmix(self) -> ServiceResult:
        if self._config is None:
            return ServiceResult(False, t("service.config_unavailable"))
        vmix_config = self._config.vmix
        vmix = VmixOutput(
            host=vmix_config.host,
            port=vmix_config.port,
            input=vmix_config.input,
            selected_name=vmix_config.selected_name,
        )
        try:
            version = vmix.test_connection()
            if not vmix_config.input:
                # no reference to "Settings": during the wizard
                # the Input/Title field is on the previous page
                return ServiceResult(
                    False,
                    t("service.vmix_missing_title"),
                )
            vmix.set_text(TEST_PHRASE)
            suffix = f" (vMix {version})" if version else ""
            return ServiceResult(
                True, t("service.vmix_test_sent", input=vmix_config.input, suffix=suffix)
            )
        except VmixError as exc:
            return ServiceResult(False, str(exc))
        except (httpx.HTTPError, httpx.InvalidURL, ValueError) as exc:
            # e.g. port pasted into the Host field → invalid URL
            logger.warning("Indirizzo vMix non valido: %s", type(exc).__name__)
            return ServiceResult(
                False,
                t("service.vmix_invalid_address", host=vmix_config.host, port=vmix_config.port),
            )
        finally:
            vmix.close()

    def list_audio_devices(self) -> list[AudioDevice]:
        try:
            return self._audio.list_devices()
        except AudioInputError as exc:
            # the dropdown will keep only "System default": at least
            # the log explains why (principle: errors are never invisible)
            logger.warning("Lettura dispositivi audio fallita: %s", exc)
            return []

    def start_audio_monitor(
        self, device_id: int | str | None, on_level: LevelCallback
    ) -> ServiceResult:
        try:
            self._audio.start(
                device_id,
                sample_rate=16000,
                channels=1,
                on_chunk=lambda chunk: on_level(rms_level(chunk)),
            )
        except AudioInputError as exc:
            return ServiceResult(False, str(exc))
        return ServiceResult(True, t("service.audio_listening"))

    def stop_audio_monitor(self) -> None:
        self._audio.stop()
