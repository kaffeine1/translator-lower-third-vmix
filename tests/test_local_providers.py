# Translator Lower Third for vMix
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""Local provider tests (v1.3) — fake engine/translator, no model download."""

from __future__ import annotations

import asyncio

import pytest

from app.providers.base import ProviderConfig
from app.providers.local_translate import (
    LocalMarianTranslationProvider,
    LocalTranslationError,
    default_model_name,
)
from app.providers.local_whisper import (
    FasterWhisperSpeechProvider,
    LocalWhisperError,
)


class FakeWhisperEngine:
    def __init__(self, **opts) -> None:
        self.opts = opts
        self.started = False
        self.stopped = False
        self.pushed: list[bytes] = []

    def start(self) -> None:
        self.started = True

    def push(self, chunk: bytes) -> None:
        self.pushed.append(chunk)

    def stop(self) -> None:
        self.stopped = True

    def emit_final(self, text: str) -> None:
        self.opts["on_final"](text)


# ---------------------------------------------------------------- Faster-Whisper


def test_whisper_connect_builds_engine_and_emits():
    engines: list[FakeWhisperEngine] = []

    def factory(**opts):
        engine = FakeWhisperEngine(**opts)
        engines.append(engine)
        return engine

    async def run():
        provider = FasterWhisperSpeechProvider(engine_factory=factory)
        finals: list[str] = []
        provider.on_final_text(finals.append)
        await provider.connect(ProviderConfig(source_language="es"))
        engine = engines[0]
        await provider.send_audio(b"\x01\x02")
        engine.emit_final("hola a todos")
        await provider.close()
        return engine, finals

    engine, finals = asyncio.run(run())
    assert engine.started and engine.stopped
    assert engine.opts["model"] == "small"
    assert engine.opts["language"] == "es"
    assert engine.pushed == [b"\x01\x02"]
    assert finals == ["hola a todos"]


def test_whisper_custom_model_and_device():
    captured = {}

    def factory(**opts):
        captured.update(opts)
        return FakeWhisperEngine(**opts)

    async def run():
        provider = FasterWhisperSpeechProvider(
            model="medium", device="cuda", engine_factory=factory
        )
        await provider.connect(ProviderConfig())
        await provider.close()

    asyncio.run(run())
    assert captured["model"] == "medium"
    assert captured["device"] == "cuda"


def test_whisper_real_engine_missing_package_is_readable():
    async def run():
        provider = FasterWhisperSpeechProvider()  # real factory
        with pytest.raises(LocalWhisperError) as excinfo:
            await provider.connect(ProviderConfig())
        assert "faster-whisper" in str(excinfo.value)

    asyncio.run(run())


def test_whisper_engine_buffer_is_capped():
    # backpressure: a slow consumer must not let the buffer grow without bound
    from app.providers.local_whisper import _WhisperEngine

    engine = _WhisperEngine(
        lambda name, device: object(),  # model never built (thread not started)
        model="small",
        device="cpu",
        sample_rate=16000,
        language="es",
        on_partial=lambda t: None,
        on_final=lambda t: None,
        on_error=lambda t: None,
    )
    engine.push(b"\x00\x00" * (16000 * 40))  # 40 s of audio, cap is 30 s
    assert len(engine._buffer) <= engine._max_bytes


def test_start_translation_surfaces_local_missing_package():
    # the local pipeline needs no credentials, so START builds it and connect()
    # fails on the missing package: the operator must see the actionable message
    from app.audio.input import FakeAudioInput
    from app.config.models import AppConfig
    from app.config.secrets import InMemorySecretStore
    from app.services import LiveAppServices

    services = LiveAppServices(FakeAudioInput(), InMemorySecretStore())
    config = AppConfig()
    config.provider = "local"
    services.update_config(config)
    result = services.start_translation()
    try:
        assert result.ok is False
        assert "faster-whisper" in result.message.lower()
    finally:
        services.stop_translation()


# ---------------------------------------------------------------- MarianMT


def test_default_model_name():
    assert default_model_name("es", "it") == "Helsinki-NLP/opus-mt-es-it"
    assert default_model_name("EN", "FR") == "Helsinki-NLP/opus-mt-en-fr"


def test_marian_translate_with_fake_model():
    captured = {}

    def factory(model_name: str):
        captured["model"] = model_name
        return lambda text: {"hola": "ciao", "hola a todos": "ciao a tutti"}.get(text, text)

    async def run():
        provider = LocalMarianTranslationProvider(translator_factory=factory)
        await provider.connect(ProviderConfig(source_language="es", target_language="it"))
        out = await provider.translate("hola a todos")
        await provider.close()
        return out

    out = asyncio.run(run())
    assert out == "ciao a tutti"
    assert captured["model"] == "Helsinki-NLP/opus-mt-es-it"


def test_marian_empty_text_skips_model():
    def factory(model_name: str):
        return lambda text: (_ for _ in ()).throw(AssertionError("non deve tradurre vuoto"))

    async def run():
        provider = LocalMarianTranslationProvider(translator_factory=factory)
        await provider.connect(ProviderConfig())
        return await provider.translate("   ")

    assert asyncio.run(run()) == ""


def test_marian_translate_failure_is_readable():
    def factory(model_name: str):
        def broken(text: str) -> str:
            raise RuntimeError("model blew up")

        return broken

    async def run():
        provider = LocalMarianTranslationProvider(translator_factory=factory)
        await provider.connect(ProviderConfig())
        with pytest.raises(LocalTranslationError):
            await provider.translate("hola")

    asyncio.run(run())


def test_marian_real_model_missing_package_is_readable():
    # the model is built lazily on first translate(): a missing package surfaces
    # there with a readable message (connect stays fast)
    async def run():
        provider = LocalMarianTranslationProvider()  # real factory
        await provider.connect(ProviderConfig())
        with pytest.raises(LocalTranslationError) as excinfo:
            await provider.translate("hola")
        assert "transformers" in str(excinfo.value)

    asyncio.run(run())


# ---------------------------------------------------------------- composed local


def test_local_composed_pipeline():
    from app.providers.composed import ComposedRealtimeProvider

    async def run():
        engines: list[FakeWhisperEngine] = []

        def whisper_factory(**opts):
            engine = FakeWhisperEngine(**opts)
            engines.append(engine)
            return engine

        def marian_factory(model_name: str):
            return lambda text: text.upper()

        speech = FasterWhisperSpeechProvider(engine_factory=whisper_factory)
        translator = LocalMarianTranslationProvider(translator_factory=marian_factory)
        composed = ComposedRealtimeProvider(speech, translator)
        finals: list[str] = []
        composed.on_final_text(finals.append)
        await composed.connect(ProviderConfig(source_language="es", target_language="it"))
        engines[0].emit_final("hola")
        # translation runs off-thread (asyncio.to_thread): poll for the result
        for _ in range(200):
            if finals:
                break
            await asyncio.sleep(0.01)
        await composed.close()
        return finals

    finals = asyncio.run(run())
    assert finals == ["HOLA"]


# ---------------------------------------------------------------- registry


def test_local_registry_entries():
    from app.providers.composed import ComposedRealtimeProvider
    from app.providers.registry import (
        available_providers,
        create_provider,
        get_provider_info,
        get_speech_provider_info,
        get_translation_provider_info,
    )

    ids = [info.id for info in available_providers()]
    assert "local" in ids
    # local pipeline needs no credentials
    assert get_provider_info("local").requires_api_key is False
    assert get_speech_provider_info("faster-whisper") is not None
    assert get_translation_provider_info("marian") is not None
    provider = create_provider("local", None)
    assert isinstance(provider, ComposedRealtimeProvider)


def test_local_speech_and_translate_not_in_realtime_selector():
    from app.providers.registry import available_providers

    ids = [info.id for info in available_providers()]
    assert "faster-whisper" not in ids
    assert "marian" not in ids


def test_config_local_model_device_roundtrip():
    from app.config.models import AppConfig

    assert AppConfig().local_model == "small"
    assert AppConfig().local_device == "cpu"
    cfg = AppConfig.from_dict({"local_model": "large-v3", "local_device": "cuda"})
    assert cfg.local_model == "large-v3"
    assert cfg.local_device == "cuda"
    # invalid device falls back to default; custom model name is kept
    bad = AppConfig.from_dict({"local_model": "custom-model", "local_device": "tpu"})
    assert bad.local_model == "custom-model"
    assert bad.local_device == "cpu"


def test_create_local_provider_uses_config_model_and_device():
    from app.config.models import AppConfig
    from app.providers.local_whisper import FasterWhisperSpeechProvider
    from app.providers.registry import create_provider, create_speech_provider

    config = AppConfig()
    config.local_model = "medium"
    config.local_device = "cuda"
    speech = create_speech_provider("faster-whisper", None, config)
    assert isinstance(speech, FasterWhisperSpeechProvider)
    assert speech._model == "medium"
    assert speech._device == "cuda"
    # via the composed realtime pipeline
    composed = create_provider("local", None, config)
    assert composed._speech._model == "medium"
    assert composed._speech._device == "cuda"


def test_create_local_provider_defaults_without_config():
    from app.providers.registry import create_speech_provider

    speech = create_speech_provider("faster-whisper", None)  # no config
    assert speech._model == "small"
    assert speech._device == "cpu"
