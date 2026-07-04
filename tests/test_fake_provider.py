# Translator Lower Third for vMix
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""FakeTranslationProvider tests (Milestone 6) — asyncio, no network."""

from __future__ import annotations

import asyncio

from app.providers.base import ProviderConfig
from app.providers.fake import DEMO_SCRIPT, FakeTranslationProvider


def _collect(provider: FakeTranslationProvider):
    partials: list[str] = []
    finals: list[str] = []
    errors: list[str] = []
    provider.on_partial_text(partials.append)
    provider.on_final_text(finals.append)
    provider.on_error(errors.append)
    return partials, finals, errors


def test_emits_partial_and_final_text():
    async def run():
        script = [("partial", "Ciao"), ("final", "Ciao a tutti")]
        provider = FakeTranslationProvider(script=script, step_delay=0.0, loop=False)
        partials, finals, errors = _collect(provider)
        await provider.connect(ProviderConfig())
        # wait for the internal task to complete
        await asyncio.wait_for(provider._task, timeout=2)
        return partials, finals, errors

    partials, finals, errors = asyncio.run(run())
    assert partials == ["Ciao"]
    assert finals == ["Ciao a tutti"]
    assert errors == []


def test_emits_error_event():
    async def run():
        provider = FakeTranslationProvider(
            script=[("partial", "a"), ("final", "b"), ("final", "c")],
            step_delay=0.0,
            fail_at_index=1,
            loop=False,
        )
        partials, finals, errors = _collect(provider)
        await provider.connect(ProviderConfig())
        await asyncio.wait_for(provider._task, timeout=2)
        return partials, finals, errors

    partials, finals, errors = asyncio.run(run())
    assert errors and "Connessione persa" in errors[0]
    # after the error no more finals arrive
    assert finals == []


def test_clean_shutdown_cancels_task():
    async def run():
        provider = FakeTranslationProvider(step_delay=10.0)  # long: does not finish
        _collect(provider)
        await provider.connect(ProviderConfig())
        task = provider._task
        assert task is not None and not task.done()
        await provider.close()
        return task

    task = asyncio.run(run())
    assert task.done()


def test_send_audio_is_accepted_and_ignored():
    async def run():
        provider = FakeTranslationProvider(step_delay=10.0)
        await provider.connect(ProviderConfig())
        await provider.send_audio(b"\x00\x01" * 100)  # must not raise
        await provider.close()

    asyncio.run(run())


def test_demo_script_has_partials_and_finals():
    kinds = {kind for kind, _ in DEMO_SCRIPT}
    assert "partial" in kinds
    assert "final" in kinds
