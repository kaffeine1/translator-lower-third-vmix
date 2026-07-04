# Translator Lower Third for vMix
# Autore: Michele Dipace <michele.dipace@kaffeine.net>
"""FakeTranslationProvider — provider di sviluppo/demo, nessun uso di API a pagamento.

Emette una sequenza scriptata di testi parziali/finali (già "tradotti" in
italiano) su una timeline asincrona, così l'intera pipeline
provider → formatter → vMix può essere provata senza microfono né OpenAI.
Può anche simulare un errore di connessione per testare la gestione errori.
"""

from __future__ import annotations

import asyncio
import logging

from app.providers.base import ProviderConfig, RealtimeTranslationProvider

logger = logging.getLogger("app.providers.fake")

# (kind, text): la demo simula il parlato spagnolo già tradotto in italiano
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
    """Emette eventi di testo scriptati senza alcun accesso di rete.

    Parametri:
    - script: sequenza (kind, text); default DEMO_SCRIPT.
    - step_delay: secondi tra un evento e il successivo.
    - fail_at_index: se impostato, emette on_error a quell'indice e si ferma.
    - loop: se True, ricomincia lo script da capo (demo continua).
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
                        self._emit_error("Connessione persa, riprovo…")
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
        except Exception:  # un provider non deve mai far cadere il loop
            logger.exception("Errore nel FakeTranslationProvider")
            self._emit_error("Errore interno del provider di traduzione")

    async def send_audio(self, chunk: bytes) -> None:
        # il provider finto ignora l'audio: emette testo su timeline propria
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
