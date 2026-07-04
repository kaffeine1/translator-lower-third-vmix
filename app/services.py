# Translator Lower Third for vMix
# Autore: Michele Dipace <michele.dipace@kaffeine.net>
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
from app.outputs.vmix import TEST_PHRASE, VmixError, VmixOutput

logger = logging.getLogger("app.services")

SubtitleCallback = Callable[[str], None]
LevelCallback = Callable[[float], None]


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
        self._config: AppConfig | None = None

    def update_config(self, config: AppConfig) -> None:
        """Configurazione corrente: la GUI la aggiorna a ogni modifica."""
        self._config = config

    def set_subtitle_listener(self, callback: SubtitleCallback | None) -> None:
        self._subtitle_listener = callback

    def set_error_listener(self, callback: SubtitleCallback | None) -> None:
        """Errori del pipeline durante la traduzione (es. vMix giù, provider
        disconnesso). Può arrivare da thread di lavoro: marshalare sul thread Qt."""
        self._error_listener = callback

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
        """Avvia l'ascolto per il Test Audio; on_level riceve livelli 0.0–1.0.

        on_level può arrivare da un thread audio: i consumatori GUI devono
        rimandarlo sul thread Qt (signal emit).
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
            return ServiceResult(False, "Impossibile aprire l'ingresso audio selezionato")
        self.monitoring = True
        for level in self.mock_levels:
            on_level(level)
        return ServiceResult(True, "Ascolto in corso… parla nel microfono")

    def stop_audio_monitor(self) -> None:
        self.monitoring = False

    def test_api(self) -> ServiceResult:
        if self.fail_api:
            return ServiceResult(False, "API key non valida")
        return ServiceResult(True, "Connessione API riuscita (demo)")

    def test_vmix(self) -> ServiceResult:
        if self.fail_vmix:
            return ServiceResult(False, "vMix non raggiungibile")
        return ServiceResult(True, "Frase di prova inviata a vMix (demo)")

    def start_translation(self) -> ServiceResult:
        self.running = True
        self._emit_subtitle("Benvenuti a questo evento dal vivo (demo)")
        return ServiceResult(True, "Traduzione avviata (demo)")

    def stop_translation(self) -> ServiceResult:
        self.running = False
        return ServiceResult(True, "Traduzione fermata")


class LiveAppServices(MockAppServices):
    """Servizi progressivamente reali: audio (M3) e vMix (M4) veri, provider
    di traduzione ancora mock fino alla Milestone 7.

    La GUI non cambia perché dipende solo dall'interfaccia AppServices.
    """

    def __init__(self, audio_input: AudioInput, secret_store: SecretStore | None = None) -> None:
        super().__init__()
        self._audio = audio_input
        self._secret_store = secret_store
        self._pipeline = None
        self._vmix: VmixOutput | None = None

    def _make_provider(self):
        """Provider di traduzione in uso, scelto dal registro in base a
        config.provider. Se il provider richiede una chiave API ma non ce n'è
        una salvata, si ricade sulla demo (finto) così la GUI resta usabile."""
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
            # logga solo i NOMI degli account mancanti, mai i valori
            logger.info(
                "Chiavi mancanti per '%s' (%s): uso il provider demo",
                provider_id,
                ", ".join(missing),
            )
            return create_provider("fake", self._secret_store)
        return create_provider(provider_id, self._secret_store)

    def _has_key(self, provider_id: str) -> bool:
        if self._secret_store is None:
            return False
        try:
            return bool(self._secret_store.get_api_key(provider_id))
        except SecretStorageError:
            return False

    def test_api(self) -> ServiceResult:
        if self._config is None:
            return ServiceResult(False, "Configurazione non disponibile")
        from app.providers.registry import get_provider_info

        provider_id = self._config.provider
        info = get_provider_info(provider_id)
        if info is not None and not info.requires_api_key:
            return ServiceResult(True, "Modalità demo: nessuna chiave API necessaria")
        if self._secret_store is None:
            return ServiceResult(False, "Configurazione non disponibile")
        try:
            key = self._secret_store.get_api_key(provider_id)
        except SecretStorageError as exc:
            return ServiceResult(False, str(exc))
        if not key:
            return ServiceResult(
                False, "Nessuna chiave API salvata. Inseriscila nelle Impostazioni."
            )
        import asyncio

        from app.providers.openai_realtime import OpenAIProviderError, check_api_key

        try:
            asyncio.run(check_api_key(self._secret_store, provider_id))
        except OpenAIProviderError as exc:
            return ServiceResult(False, str(exc))
        except Exception:
            logger.exception("Verifica API fallita")
            return ServiceResult(
                False, "Impossibile verificare la chiave API. Consulta i log."
            )
        return ServiceResult(True, "Connessione API riuscita")

    def start_translation(self) -> ServiceResult:
        if self._config is None:
            return ServiceResult(False, "Configurazione non disponibile")
        if self._pipeline is not None:
            return ServiceResult(True, "Traduzione già avviata")

        from app.pipeline import TranslationPipeline

        vmix_config = self._config.vmix
        vmix = VmixOutput(
            host=vmix_config.host,
            port=vmix_config.port,
            input=vmix_config.input,
            selected_name=vmix_config.selected_name,
        )
        # notifica l'errore vMix una sola volta finché persiste, per non
        # inondare l'operatore a ogni sottotitolo
        vmix_error_shown = {"flag": False}

        def publish_to_vmix(text: str) -> None:
            try:
                vmix.set_text(text)
                vmix_error_shown["flag"] = False
            except VmixError as exc:
                if not vmix_error_shown["flag"]:
                    vmix_error_shown["flag"] = True
                    self._emit_error(str(exc))

        pipeline = TranslationPipeline(
            self._make_provider(),
            self._config,
            on_subtitle=self._emit_subtitle,
            output_publish=publish_to_vmix,
            on_error=self._emit_error,
            audio_input=self._audio,
        )
        try:
            pipeline.start()
        except Exception:
            logger.exception("Avvio pipeline fallito")
            vmix.close()
            return ServiceResult(
                False, "Impossibile avviare la traduzione. Consulta i log."
            )
        self._pipeline = pipeline
        self._vmix = vmix
        self.running = True
        return ServiceResult(True, "Traduzione avviata")

    def stop_translation(self) -> ServiceResult:
        if self._pipeline is not None:
            self._pipeline.stop()
            self._pipeline = None
        if self._vmix is not None:
            try:
                self._vmix.clear_text()  # svuota il titolo a fine diretta
            except VmixError:
                pass
            self._vmix.close()
            self._vmix = None
        self.running = False
        return ServiceResult(True, "Traduzione fermata")

    def test_vmix(self) -> ServiceResult:
        if self._config is None:
            return ServiceResult(False, "Configurazione non disponibile")
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
                # niente riferimento alle "Impostazioni": durante il wizard
                # il campo Input/Titolo è nella pagina precedente
                return ServiceResult(
                    False,
                    "vMix raggiungibile, ma manca il nome del titolo: "
                    "compila il campo Input/Titolo.",
                )
            vmix.set_text(TEST_PHRASE)
            suffix = f" (vMix {version})" if version else ""
            return ServiceResult(
                True, f'Frase di prova inviata al titolo "{vmix_config.input}"{suffix}'
            )
        except VmixError as exc:
            return ServiceResult(False, str(exc))
        except (httpx.HTTPError, httpx.InvalidURL, ValueError) as exc:
            # es. porta incollata dentro al campo Host → URL non valido
            logger.warning("Indirizzo vMix non valido: %s", type(exc).__name__)
            return ServiceResult(
                False,
                f'Indirizzo vMix non valido ("{vmix_config.host}:{vmix_config.port}"). '
                "Controlla i campi Host e Porta: l'host non deve contenere la porta.",
            )
        finally:
            vmix.close()

    def list_audio_devices(self) -> list[AudioDevice]:
        try:
            return self._audio.list_devices()
        except AudioInputError as exc:
            # la tendina resterà con il solo "Predefinito di sistema": almeno
            # il log spiega perché (principio: errori mai invisibili)
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
        return ServiceResult(True, "Ascolto in corso… parla nel microfono")

    def stop_audio_monitor(self) -> None:
        self._audio.stop()
