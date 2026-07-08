# Traduttore Live
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


def test_whisper_real_engine_missing_package_is_readable(monkeypatch):
    # simulate the absent optional package via sys.modules so the test stays
    # deterministic when faster-whisper IS installed in the dev environment
    import sys

    monkeypatch.setitem(sys.modules, "faster_whisper", None)

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


def test_start_translation_surfaces_local_missing_package(monkeypatch):
    # the local pipeline needs no credentials, so START builds it and connect()
    # fails on the missing package: the operator must see the actionable message.
    # A None sys.modules entry makes the import raise even when the optional
    # package IS installed in the dev environment (determinism).
    import sys

    from app.audio.input import FakeAudioInput
    from app.config.models import AppConfig
    from app.config.secrets import InMemorySecretStore
    from app.services import LiveAppServices

    monkeypatch.setitem(sys.modules, "faster_whisper", None)
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


def test_marian_real_model_missing_package_is_readable(monkeypatch):
    # the model is built lazily on first translate(): a missing package surfaces
    # there with a readable message (connect stays fast). Simulate the absence
    # via sys.modules so the test does not depend on the dev environment (and
    # never downloads a real model when transformers IS installed).
    import sys

    monkeypatch.setitem(sys.modules, "torch", None)
    monkeypatch.setitem(sys.modules, "transformers", None)

    async def run():
        provider = LocalMarianTranslationProvider()  # real factory
        await provider.connect(ProviderConfig())
        with pytest.raises(LocalTranslationError) as excinfo:
            await provider.translate("hola")
        # operator-readable message that points at the log or the downloader
        msg = str(excinfo.value)
        assert "componenti" in msg.lower()

    asyncio.run(run())


def test_local_component_error_distinguishes_missing_vs_broken():
    from app.providers.local_translate import _local_component_error

    # a genuinely absent package (import x fails with x itself missing) -> download
    missing = _local_component_error(ModuleNotFoundError("No module named 'torch'", name="torch"))
    assert "Scarica" in missing
    # a stdlib sub-dependency missing deep inside a PRESENT package (torch ->
    # timeit) is a broken environment, not a missing download -> point at the log
    subdep = _local_component_error(ModuleNotFoundError("No module named 'timeit'", name="timeit"))
    assert "Log" in subdep or "Visual C++" in subdep
    # a DLL load error -> also broken/see the log
    broken = _local_component_error(ImportError("DLL load failed while importing torch"))
    assert "Log" in broken or "Visual C++" in broken
    assert missing != subdep


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


# ---------------------------------------------------------------- ordering / build race


def test_composed_finals_keep_speech_order_with_slow_translator():
    # two finals in flight: the FIRST one is slower to translate. Without the
    # serialization the second would reach the air first and captions would swap.
    from app.providers.composed import ComposedRealtimeProvider

    class SlowFirstTranslator:
        async def connect(self, config) -> None: ...
        async def close(self) -> None: ...

        async def translate(self, text: str) -> str:
            await asyncio.sleep(0.2 if text == "prima frase" else 0.0)
            return text.upper()

    async def run():
        engines: list[FakeWhisperEngine] = []

        def factory(**opts):
            engine = FakeWhisperEngine(**opts)
            engines.append(engine)
            return engine

        speech = FasterWhisperSpeechProvider(engine_factory=factory)
        provider = ComposedRealtimeProvider(speech, SlowFirstTranslator())
        finals: list[str] = []
        provider.on_final_text(finals.append)
        await provider.connect(ProviderConfig())
        engines[0].emit_final("prima frase")
        engines[0].emit_final("seconda frase")
        await asyncio.sleep(0.5)  # let both translations complete
        await provider.close()
        assert finals == ["PRIMA FRASE", "SECONDA FRASE"]  # speech order preserved

    asyncio.run(run())


def test_marian_concurrent_first_translations_build_model_once():
    # the lazy model build runs on to_thread workers: concurrent first calls
    # must share ONE build (each real build costs hundreds of MB of RAM)
    import time

    builds = []

    def factory(model_name: str):
        builds.append(model_name)
        time.sleep(0.05)  # widen the race window
        return lambda text: text.upper()

    async def run():
        provider = LocalMarianTranslationProvider(translator_factory=factory)
        await provider.connect(ProviderConfig())
        results = await asyncio.gather(*(provider.translate(f"testo {i}") for i in range(4)))
        assert sorted(results) == [f"TESTO {i}" for i in range(4)]
        assert len(builds) == 1  # a single model build despite the concurrency

    asyncio.run(run())


# ---------------------------------------------------------------- same-language passthrough


def test_composed_same_language_skips_translator_and_passes_text_through():
    # source == target = captioning without translation (e.g. it -> it): the
    # recognized text must go on air as-is and the translator must never run
    from app.providers.composed import ComposedRealtimeProvider

    class ExplodingTranslator:
        connected = False

        async def connect(self, config) -> None:
            self.connected = True

        async def close(self) -> None: ...

        async def translate(self, text: str) -> str:
            raise AssertionError("translator must not run in passthrough mode")

    async def run():
        engines: list[FakeWhisperEngine] = []

        def factory(**opts):
            engine = FakeWhisperEngine(**opts)
            engines.append(engine)
            return engine

        translator = ExplodingTranslator()
        speech = FasterWhisperSpeechProvider(engine_factory=factory)
        provider = ComposedRealtimeProvider(speech, translator)
        partials: list[str] = []
        finals: list[str] = []
        provider.on_partial_text(partials.append)
        provider.on_final_text(finals.append)
        await provider.connect(
            ProviderConfig(source_language="it", target_language="IT")  # case-insensitive
        )
        engines[0].opts["on_partial"]("buona")
        engines[0].emit_final("buonasera a tutti")
        await asyncio.sleep(0)  # nothing scheduled, but keep the loop honest
        await provider.close()
        assert translator.connected is False  # translator never even connected
        return partials, finals

    partials, finals = asyncio.run(run())
    assert partials == ["buona"]
    assert finals == ["buonasera a tutti"]


def test_composed_different_languages_still_translate():
    from app.providers.composed import ComposedRealtimeProvider

    class UpperTranslator:
        async def connect(self, config) -> None: ...
        async def close(self) -> None: ...

        async def translate(self, text: str) -> str:
            return text.upper()

    async def run():
        engines: list[FakeWhisperEngine] = []

        def factory(**opts):
            engine = FakeWhisperEngine(**opts)
            engines.append(engine)
            return engine

        speech = FasterWhisperSpeechProvider(engine_factory=factory)
        provider = ComposedRealtimeProvider(speech, UpperTranslator())
        finals: list[str] = []
        provider.on_final_text(finals.append)
        await provider.connect(ProviderConfig(source_language="it", target_language="en"))
        engines[0].emit_final("buonasera")
        await asyncio.sleep(0.1)
        await provider.close()
        return finals

    assert asyncio.run(run()) == ["BUONASERA"]


# ---------------------------------------------------------------- silence-aware segmentation


def _engine(sample_rate: int = 16000, device: str = "cpu"):
    from app.providers.local_whisper import _WhisperEngine

    return _WhisperEngine(
        lambda name, device: object(),  # model never built (thread not started)
        model="small",
        device=device,
        sample_rate=sample_rate,
        language="it",
        on_partial=lambda t: None,
        on_final=lambda t: None,
        on_error=lambda t: None,
    )


def _pcm(seconds: float, amplitude: int, sample_rate: int = 16000) -> bytes:
    import numpy as np

    n = int(sample_rate * seconds)
    return np.full(n, amplitude, dtype="<i2").tobytes()


def test_take_segment_none_when_short_and_not_idle():
    engine = _engine()
    engine.push(_pcm(0.5, 8000))
    assert engine._take_segment() is None


def test_take_segment_cuts_at_pause():
    # 2s speech + 0.6s pause + 2s speech: the cut must land inside the pause,
    # never bisecting the second phrase
    engine = _engine()
    pushed = _pcm(2.0, 8000) + _pcm(0.6, 0) + _pcm(2.0, 8000)
    engine.push(pushed)
    segment = engine._take_segment()
    assert segment is not None
    assert len(segment) % engine._frame_bytes == 0  # sample-aligned cut
    assert len(_pcm(2.0, 8000)) < len(segment) <= len(_pcm(2.6, 8000))
    # OVERLAP_SECONDS of the tail is retained for the next segment, so buffer
    # starts overlap_bytes before the cut; dropping that overlap conserves audio
    cut = len(segment)
    assert segment == pushed[:cut]
    assert bytes(engine._buffer) == pushed[cut - engine._overlap_bytes :]


def test_take_segment_ignores_pause_before_min_segment():
    # a pause before MIN_SEGMENT_SECONDS must not produce a degenerate cut:
    # the cut lands in the SECOND pause
    engine = _engine()
    engine.push(
        _pcm(0.3, 8000) + _pcm(0.6, 0) + _pcm(1.5, 8000) + _pcm(0.6, 0) + _pcm(0.5, 8000)
    )
    segment = engine._take_segment()
    assert segment is not None
    assert len(segment) >= engine._min_segment_bytes
    assert len(segment) > len(_pcm(2.4, 8000))  # beyond the second phrase


def test_take_segment_hard_cap_cuts_at_quietest_frame():
    # unbroken speech with a single 30ms dip at 5.5s: the hard cap must cut
    # there (the closest thing to a pause), not mid-word at the cap itself
    engine = _engine()
    audio = bytearray(_pcm(7.0, 8000))  # beyond the 6 s hard cap
    dip = _pcm(0.03, 100)
    start = len(_pcm(5.5, 8000))  # a quiet frame within the last second before the cap
    audio[start : start + len(dip)] = dip
    engine.push(bytes(audio))
    segment = engine._take_segment()
    assert segment is not None
    assert len(segment) <= engine._max_segment_bytes
    cut_seconds = len(segment) / 32000.0
    assert abs(cut_seconds - 5.5) <= 0.06  # within ~a frame of the dip


def test_take_segment_hard_cap_without_dip():
    # uniform unbroken speech: cut at the cap itself (not a second early)
    engine = _engine()
    engine.push(_pcm(7.0, 8000))
    segment = engine._take_segment()
    assert segment is not None
    assert engine._max_segment_bytes - engine._frame_bytes <= len(segment)
    assert len(segment) <= engine._max_segment_bytes


def test_idle_flush_flushes_trailing_audio():
    import time as time_mod

    from app.providers.local_whisper import IDLE_FLUSH_SECONDS

    engine = _engine()
    pushed = _pcm(0.5, 8000)
    engine.push(pushed)
    engine._last_push = time_mod.monotonic() - IDLE_FLUSH_SECONDS - 0.1
    segment = engine._take_segment()
    assert segment == pushed
    assert not engine._buffer


def test_segments_cover_all_audio_with_overlap():
    # every pushed byte must appear in at least one segment (no gaps). Segments
    # now overlap by OVERLAP_SECONDS, so their concatenation is longer than the
    # input, but reconstructing by trimming each segment's leading overlap must
    # rebuild the original exactly (no audio lost).
    import time as time_mod

    from app.providers.local_whisper import IDLE_FLUSH_SECONDS

    engine = _engine()
    pushed = b"".join(_pcm(2.0, 8000) + _pcm(0.6, 0) for _ in range(5))
    engine.push(pushed)
    segments = []
    while True:
        segment = engine._take_segment()
        if segment is None:
            break
        segments.append(segment)
    engine._last_push = time_mod.monotonic() - IDLE_FLUSH_SECONDS - 0.1
    tail = engine._take_segment()
    if tail:
        segments.append(tail)
    rebuilt = segments[0] + b"".join(s[engine._overlap_bytes :] for s in segments[1:])
    assert rebuilt == pushed  # all audio covered, nothing lost


def test_silence_gate():
    engine = _engine()
    assert engine._is_silent(_pcm(1.0, 0)) is True
    assert engine._is_silent(_pcm(1.0, 8000)) is False


def test_transcribe_passes_live_tuned_options():
    captured = {}

    class StubModel:
        def transcribe(self, audio, **kwargs):
            captured.update(kwargs)
            return [], None

    engine = _engine(device="cpu")
    engine._model = StubModel()
    engine._transcribe(_pcm(2.0, 8000))
    assert captured["vad_filter"] is True
    assert captured["condition_on_previous_text"] is False  # never (loop floods)
    # recall-first defaults so real words are not dropped
    assert captured["no_speech_threshold"] == 0.6
    assert captured["log_prob_threshold"] == -1.0
    # the expensive levers are CPU-cheap here (realtime budget)
    assert captured["beam_size"] == 1
    assert captured["temperature"] == 0.0


def test_transcribe_uses_gpu_recall_settings_on_cuda():
    captured = {}

    class StubModel:
        def transcribe(self, audio, **kwargs):
            captured.update(kwargs)
            return [], None

    engine = _engine(device="cuda")
    engine._model = StubModel()
    engine._transcribe(_pcm(2.0, 8000))
    # on GPU we can afford beam search + a temperature fallback for recall
    assert captured["beam_size"] == 5
    assert captured["temperature"] == (0.0, 0.2, 0.4, 0.6)


def test_transcribe_dedups_overlap_and_carries_context():
    # the overlap region is transcribed twice: the leading words that repeat the
    # previous emit's tail must be dropped, and the tail is carried forward
    finals: list[str] = []

    class StubModel:
        def __init__(self):
            self._texts = iter(
                ["il nostro sistema cattura", "sistema cattura l audio in tempo reale"]
            )

        def transcribe(self, audio, **kwargs):
            class Seg:
                text = next(self._model_texts)

            return [Seg()], None

    engine = _engine()
    stub = StubModel()
    engine._model = stub
    stub._model_texts = stub._texts
    engine._on_final = finals.append
    engine._transcribe(_pcm(2.0, 8000))
    engine._transcribe(_pcm(2.0, 8000))
    # the doubled "sistema cattura" is removed from the second emit
    assert finals == ["il nostro sistema cattura", "l audio in tempo reale"]
    assert engine._prev_tail_words == "l audio in tempo reale".split()[-12:]


# ------------------------------------------------------------------ GPU load error


def test_whisper_gpu_load_failure_is_actionable(caplog):
    # a failed model load on CUDA must yield the GPU-specific, actionable
    # message (and log a full traceback for diagnosis)
    import logging

    from app.i18n import t
    from app.providers.local_whisper import _WhisperEngine

    def boom_model(name, device):
        raise RuntimeError("Library cublas64_12.dll is not found")

    errors: list[str] = []
    engine = _WhisperEngine(
        boom_model,
        model="large-v3",
        device="cuda",
        sample_rate=16000,
        language="it",
        on_partial=lambda _t: None,
        on_final=lambda _t: None,
        on_error=errors.append,
    )
    with caplog.at_level(logging.WARNING):
        engine._run()  # synchronous: model load fails immediately
    assert errors == [t("local.whisper_gpu_load_failed")]
    assert any(r.exc_info for r in caplog.records)  # traceback captured


def test_whisper_cpu_load_failure_uses_generic_message():
    from app.i18n import t
    from app.providers.local_whisper import _WhisperEngine

    def boom_model(name, device):
        raise RuntimeError("boom")

    errors: list[str] = []
    engine = _WhisperEngine(
        boom_model,
        model="small",
        device="cpu",
        sample_rate=16000,
        language="it",
        on_partial=lambda _t: None,
        on_final=lambda _t: None,
        on_error=errors.append,
    )
    engine._run()
    assert errors == [t("local.whisper_model_load_failed")]


def test_transcriptions_are_serialized_across_engines():
    # two engines encoding at once corrupted the heap (0xc0000374): the global
    # lock must prevent their transcribe() calls from overlapping
    import threading
    import time

    from app.providers.local_whisper import _WhisperEngine

    concurrency = {"now": 0, "max": 0}
    clock_lock = threading.Lock()

    class Seg:
        text = "ciao"

    class BlockingModel:
        def __init__(self, name, device):
            pass

        def transcribe(self, audio, **kw):
            with clock_lock:
                concurrency["now"] += 1
                concurrency["max"] = max(concurrency["max"], concurrency["now"])
            time.sleep(0.05)  # hold the "encode" so an overlap would be visible
            with clock_lock:
                concurrency["now"] -= 1
            return [Seg()], None

    def make_engine():
        return _WhisperEngine(
            BlockingModel,
            model="small",
            device="cpu",
            sample_rate=16000,
            language="it",
            on_partial=lambda _t: None,
            on_final=lambda _t: None,
            on_error=lambda _t: None,
        )

    seg = b"\x10\x00" * 16000  # 1 s of non-silent PCM16
    engines = [make_engine(), make_engine()]
    for e in engines:
        e._model = BlockingModel("small", "cpu")
    threads = [threading.Thread(target=e._transcribe, args=(seg,)) for e in engines]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=3)
    assert concurrency["max"] == 1  # never two encodes at once


# ---------------------------------------------------------------- streaming partials


class _ScriptedModel:
    """transcribe() returns the next scripted text each call (partials grow)."""

    def __init__(self, texts):
        self._it = iter(texts)

    def transcribe(self, audio, **kwargs):
        seg = type("Seg", (), {"text": next(self._it)})()
        return [seg], None


def test_partial_commits_only_agreed_prefix_and_is_append_only():
    # LocalAgreement-2: emit only the word prefix two consecutive runs agree on;
    # the shown text is append-only (never rewrites a shown word) -> no flicker
    engine = _engine(device="cpu")
    engine._model = _ScriptedModel(
        [
            "il nostro sistema",  # run 1: no previous -> commit nothing
            "il nostro sistema cattura l",  # run 2: agrees "il nostro sistema" (+ volatile tail)
            "il nostro sistema cattura l audio",  # run 3: agrees "...cattura l"
        ]
    )
    emitted: list[str] = []
    engine._on_partial = emitted.append

    engine._transcribe_partial(_pcm(1.0, 8000))
    engine._transcribe_partial(_pcm(2.0, 8000))
    engine._transcribe_partial(_pcm(3.0, 8000))

    assert emitted == ["il nostro sistema", "il nostro sistema cattura l"]
    # append-only: each emit extends the previous
    assert emitted[1].startswith(emitted[0])


def test_partial_never_rewrites_a_shown_word():
    # Re-transcribing the whole buffer can bring an already-shown word back
    # spelled differently. Committed words are frozen by VALUE, so the revised
    # spelling must never reach the screen (that would be flicker).
    engine = _engine(device="cpu")
    engine._model = _ScriptedModel(
        [
            "il nostro sistema",  # run 1: nothing committed yet
            "il nostro sistema cattura",  # run 2: commits "il nostro sistema"
            "il nostro sistemi cattura audio",  # run 3: "sistema" -> "sistemi"
        ]
    )
    emitted: list[str] = []
    engine._on_partial = emitted.append

    engine._transcribe_partial(_pcm(1.0, 8000))
    engine._transcribe_partial(_pcm(2.0, 8000))
    engine._transcribe_partial(_pcm(3.0, 8000))

    # the revised spelling is refused; the shown text stays frozen
    assert all("sistemi" not in e for e in emitted)
    assert emitted == ["il nostro sistema", "il nostro sistema"]


def test_final_resets_partial_state():
    engine = _engine(device="cpu")
    engine._stabilizer.feed("a b c")
    engine._stabilizer.feed("a b c")  # commit some words
    assert engine._stabilizer._committed  # sanity: not empty before the final
    engine._model = _ScriptedModel(["frase finale"])
    engine._transcribe(_pcm(1.0, 8000))
    assert engine._stabilizer._prev == []
    assert engine._stabilizer._committed == []


def test_composed_skips_identical_source_partials():
    from app.providers.composed import ComposedRealtimeProvider

    translated: list[str] = []

    class CountingTranslator:
        calls = 0

        async def connect(self, config) -> None: ...
        async def close(self) -> None: ...

        async def translate(self, text: str) -> str:
            type(self).calls += 1
            return text.upper()

    async def run():
        engines: list[FakeWhisperEngine] = []

        def factory(**opts):
            e = FakeWhisperEngine(**opts)
            engines.append(e)
            return e

        speech = FasterWhisperSpeechProvider(engine_factory=factory)
        provider = ComposedRealtimeProvider(speech, CountingTranslator())
        provider.on_partial_text(translated.append)
        await provider.connect(ProviderConfig(source_language="it", target_language="en"))
        on_partial = engines[0].opts["on_partial"]
        on_partial("il nostro")
        on_partial("il nostro")  # identical -> skipped, no re-translate
        on_partial("il nostro sistema")
        await asyncio.sleep(0.1)
        await provider.close()
        return CountingTranslator.calls

    calls = asyncio.run(run())
    assert calls == 2  # the duplicate did not trigger a translation


# ---------------------------------------------------------------- GPU compute type


def test_default_compute_type_is_device_aware():
    from app.providers.local_whisper import _default_compute_type

    # CUDA: int8_float16 (DP4A INT8 is fast on tensor-core-less Turing; float16
    # is not) — CPU: unchanged library default
    assert _default_compute_type("cuda") == "int8_float16"
    assert _default_compute_type("cpu") == "default"


def test_engine_passes_compute_type_to_model():
    from app.providers.local_whisper import _WhisperEngine

    captured = {}

    class CaptureModel:
        def __init__(self, name, device, compute_type):
            captured["device"] = device
            captured["compute_type"] = compute_type

        def transcribe(self, *a, **k):  # pragma: no cover - never called here
            return [], None

    def build(device, compute_type=None):
        engine = _WhisperEngine(
            CaptureModel,
            model="small",
            device=device,
            sample_rate=16000,
            language="it",
            on_partial=lambda _t: None,
            on_final=lambda _t: None,
            on_error=lambda _t: None,
            compute_type=compute_type,
        )
        engine._closed = True  # build the model, then exit the run loop at once
        engine._run()
        return dict(captured)

    # CUDA auto -> int8_float16
    got = build("cuda")
    assert got == {"device": "cuda", "compute_type": "int8_float16"}
    # explicit override wins
    got = build("cuda", compute_type="float16")
    assert got["compute_type"] == "float16"
    # CPU auto -> default (unchanged)
    got = build("cpu")
    assert got["compute_type"] == "default"


# ---------------------------------------------------------------- translation model errors


def test_make_real_translator_missing_model_is_actionable(monkeypatch):
    transformers = pytest.importorskip("transformers")
    pytest.importorskip("torch")
    from app.providers import local_translate

    def boom(*a, **k):
        raise OSError("model not found locally and offline")

    monkeypatch.setattr(transformers.AutoTokenizer, "from_pretrained", boom)
    with pytest.raises(LocalTranslationError) as excinfo:
        local_translate._make_real_translator("Helsinki-NLP/opus-mt-es-it")
    # points the operator at the Settings model downloader
    assert "Scarica" in str(excinfo.value)


def test_composed_surfaces_translation_provider_error_message():
    # a translator failure with an actionable message must reach the operator,
    # not be replaced by the generic "translation error"
    from app.providers.base import ProviderError
    from app.providers.composed import ComposedRealtimeProvider

    class MissingModelTranslator:
        async def connect(self, config) -> None: ...
        async def close(self) -> None: ...

        async def translate(self, text: str) -> str:
            raise ProviderError("Modello di traduzione non ancora scaricato. Scarica i modelli.")

    async def run():
        engines: list[FakeWhisperEngine] = []

        def factory(**opts):
            engine = FakeWhisperEngine(**opts)
            engines.append(engine)
            return engine

        speech = FasterWhisperSpeechProvider(engine_factory=factory)
        provider = ComposedRealtimeProvider(speech, MissingModelTranslator())
        errors: list[str] = []
        provider.on_error(errors.append)
        await provider.connect(ProviderConfig(source_language="es", target_language="it"))
        engines[0].emit_final("hola a todos")
        await asyncio.sleep(0.1)
        await provider.close()
        return errors

    errors = asyncio.run(run())
    assert errors == ["Modello di traduzione non ancora scaricato. Scarica i modelli."]
