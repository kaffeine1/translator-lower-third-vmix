# Translator Lower Third for vMix
# Autore: Michele Dipace <michele.dipace@kaffeine.net>
"""SubtitleFormatter — buffer anti-sfarfallio per il sottopancia live.

Regole (da SubtitleConfig):
- i FINALI si pubblicano subito;
- i PARZIALI si pubblicano solo se stabili da min_update_interval_ms, oppure
  — per non lasciare il sottopancia vuoto durante frasi lunghe — a cadenza
  massima di un aggiornamento ogni min_update_interval_ms;
- mai due pubblicazioni identiche consecutive;
- il testo va a capo per parole su max_lines righe da max_chars_per_line;
  se eccede si tengono le ULTIME righe (in diretta contano le parole recenti);
- dopo clear_after_silence_seconds senza testo il sottopancia si svuota,
  ma mai prima di hold_seconds dall'ultima pubblicazione.

Il formatter è guidato dall'esterno: feed_partial/feed_final dagli eventi del
provider (anche da thread di lavoro) e tick() periodico dal pipeline. Il
callback publish deve essere veloce e non bloccante (accodare, non fare HTTP).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from app.config.models import SubtitleConfig

PublishCallback = Callable[[str], None]


def clean_text(text: str) -> str:
    """Normalizza gli spazi (i provider emettono spesso spazi doppi/finali)."""
    return " ".join(text.split())


def wrap_lines(text: str, max_chars: int, max_lines: int) -> list[str]:
    """A capo per parole; le parole più lunghe di una riga vengono tagliate.

    Se il testo supera max_lines righe si tengono le ultime: in un sottopancia
    live le parole più recenti sono quelle che l'operatore vuole in onda.
    """
    lines: list[str] = []
    current = ""
    for word in text.split():
        while len(word) > max_chars:
            if current:
                lines.append(current)
                current = ""
            lines.append(word[:max_chars])
            word = word[max_chars:]
        if not word:
            continue
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[-max_lines:] if len(lines) > max_lines else lines


class SubtitleFormatter:
    def __init__(
        self,
        config: SubtitleConfig,
        publish: PublishCallback,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config
        self._publish_cb = publish
        self._clock = clock
        self._lock = threading.Lock()
        self._last_published: str | None = None  # None = mai pubblicato/reset
        self._last_publish_time = float("-inf")
        self._pending = ""
        self._pending_since = 0.0  # ultimo cambiamento del parziale
        self._pending_first_seen = 0.0  # inizio della frase corrente
        self._last_activity: float | None = None  # ultimo testo dal provider

    # ------------------------------------------------------------------ input

    def feed_partial(self, text: str) -> None:
        cleaned = clean_text(text)
        if not cleaned:
            return
        with self._lock:
            now = self._clock()
            self._last_activity = now
            if not self._pending:
                self._pending_first_seen = now
            if cleaned != self._pending:
                self._pending = cleaned
                self._pending_since = now
            self._maybe_publish_partial(now)

    def feed_final(self, text: str) -> None:
        cleaned = clean_text(text)
        if not cleaned:
            return
        with self._lock:
            now = self._clock()
            self._last_activity = now
            self._pending = ""
            self._publish(cleaned, now)

    def tick(self) -> None:
        """Da chiamare periodicamente (~250 ms): gestisce stabilità dei
        parziali e pulizia dopo silenzio."""
        with self._lock:
            now = self._clock()
            self._maybe_publish_partial(now)
            self._maybe_clear_after_silence(now)

    def reset(self) -> None:
        """Stato pulito (per STOP). Non pubblica nulla: è il pipeline a
        decidere se svuotare anche il titolo in vMix."""
        with self._lock:
            self._pending = ""
            self._last_published = None
            self._last_publish_time = float("-inf")
            self._last_activity = None

    # ------------------------------------------------------------------ logica

    def _interval_s(self) -> float:
        return self._config.min_update_interval_ms / 1000.0

    def _maybe_publish_partial(self, now: float) -> None:
        if not self._pending:
            return
        interval = self._interval_s()
        stable = now - self._pending_since >= interval
        cadence = (
            now - self._pending_first_seen >= interval
            and now - self._last_publish_time >= interval
        )
        if stable or cadence:
            self._publish(self._pending, now)

    def _maybe_clear_after_silence(self, now: float) -> None:
        clear_after = self._config.clear_after_silence_seconds
        if clear_after <= 0:
            return
        if not self._last_published:  # niente in onda: nulla da pulire
            return
        if self._last_activity is None or now - self._last_activity < clear_after:
            return
        if now - self._last_publish_time < self._config.hold_seconds:
            return
        # il parziale in sospeso va scartato: senza questo, un parziale mai
        # finalizzato risorgerebbe al tick successivo e il sottopancia
        # lampeggerebbe all'infinito testo/vuoto
        self._pending = ""
        self._publish_cb("")
        self._last_published = ""
        self._last_publish_time = now

    def _publish(self, text: str, now: float) -> None:
        lines = wrap_lines(text, self._config.max_chars_per_line, self._config.max_lines)
        joined = "\n".join(lines)
        if joined == self._last_published:
            return
        self._publish_cb(joined)
        self._last_published = joined
        self._last_publish_time = now
