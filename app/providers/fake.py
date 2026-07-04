# Translator Lower Third for vMix
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""FakeTranslationProvider — development/demo provider, no paid API usage.

Emits a scripted sequence of partial/final texts (already "translated" into
Italian) on an asynchronous timeline, so the whole
provider → formatter → vMix pipeline can be exercised without a microphone or
OpenAI. It can also simulate a connection error to test error handling.
"""

from __future__ import annotations

import asyncio
import logging

from app.i18n import t
from app.providers.base import ProviderConfig, RealtimeTranslationProvider

logger = logging.getLogger("app.providers.fake")

# (kind, text): the demo simulates Spanish speech already translated into Italian
DEMO_SCRIPT: list[tuple[str, str]] = [
    ("partial", "Benvenuti"),
    ("partial", "Benvenuti a questo"),
    ("final", "Benvenuti a questo evento dal vivo."),
    ("partial", "Oggi"),
    ("partial", "Oggi parliamo di"),
    ("final", "Oggi parliamo di tecnologia e innovazione."),
    ("partial", "Grazie"),
    ("final", "Grazie a tutti per la partecipazione."),
]


class FakeTranslationProvider(RealtimeTranslationProvider):
    """Emits scripted text events without any network access.

    Parameters:
    - script: (kind, text) sequence; defaults to DEMO_SCRIPT.
    - step_delay: seconds between one event and the next.
    - fail_at_index: if set, emits on_error at that index and stops.
    - loop: if True, restarts the script from the beginning (continuous demo).
    """

    def __init__(
        self,
        script: list[tuple[str, str]] | None = None,
        step_delay: float = 0.8,
        fail_at_index: int | None = None,
        loop: bool = True,
    ) -> None:
        super().__init__()
        self._script = script if script is not None else DEMO_SCRIPT
        self._step_delay = step_delay
        self._fail_at_index = fail_at_index
        self._loop = loop
        self._task: asyncio.Task | None = None
        self._closed = False

    async def connect(self, config: ProviderConfig) -> None:
        self._closed = False
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            index = 0
            while not self._closed:
                for kind, text in self._script:
                    if self._closed:
                        return
                    await asyncio.sleep(self._step_delay)
                    if self._fail_at_index is not None and index >= self._fail_at_index:
                        self._emit_error(t("provider.connection_lost"))
                        return
                    if kind == "partial":
                        self._emit_partial(text)
                    else:
                        self._emit_final(text)
                    index += 1
                if not self._loop:
                    return
        except asyncio.CancelledError:
            raise
        except Exception:  # a provider must never let the loop crash
            logger.exception("Errore nel FakeTranslationProvider")
            self._emit_error(t("provider.internal_error"))

    async def send_audio(self, chunk: bytes) -> None:
        # the fake provider ignores audio: it emits text on its own timeline
        return None

    async def close(self) -> None:
        self._closed = True
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
