# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""SubtitleFormatter — anti-flicker buffer for the live lower third.

Rules (from SubtitleConfig):
- FINALS are published immediately;
- PARTIALS are published only if stable for min_update_interval_ms, or
  — to avoid leaving the lower third empty during long sentences — at a maximum
  cadence of one update every min_update_interval_ms;
- never two identical consecutive publications;
- the text wraps by words onto max_lines lines of max_chars_per_line;
  if it exceeds, the LAST lines are kept (live, the recent words matter);
- after clear_after_silence_seconds without text the lower third is cleared,
  but never before hold_seconds since the last publication.

The formatter is driven externally: feed_partial/feed_final from the
provider's events (including from worker threads) and periodic tick() from the
pipeline. The publish callback must be fast and non-blocking (enqueue, no HTTP).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from app.config.models import SubtitleConfig

PublishCallback = Callable[[str], None]


def clean_text(text: str) -> str:
    """Normalize whitespace (providers often emit double/trailing spaces)."""
    return " ".join(text.split())


def wrap_lines(text: str, max_chars: int, max_lines: int) -> list[str]:
    """Word wrap; words longer than a line are split.

    If the text exceeds max_lines lines, the last ones are kept: in a live
    lower third the most recent words are the ones the operator wants on air.
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
        self._last_published: str | None = None  # None = never published/reset
        self._last_publish_time = float("-inf")
        self._pending = ""
        self._pending_since = 0.0  # last change of the partial
        self._pending_first_seen = 0.0  # start of the current sentence
        self._last_activity: float | None = None  # last text from the provider

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
        """Call periodically (~250 ms): handles partial stability
        and clearing after silence."""
        with self._lock:
            now = self._clock()
            self._maybe_publish_partial(now)
            self._maybe_clear_after_silence(now)

    def reset(self) -> None:
        """Clean state (for STOP). Publishes nothing: it is the pipeline that
        decides whether to also clear the title in vMix."""
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
        if not self._last_published:  # nothing on air: nothing to clear
            return
        if self._last_activity is None or now - self._last_activity < clear_after:
            return
        if now - self._last_publish_time < self._config.hold_seconds:
            return
        # the pending partial must be discarded: without this, a partial never
        # finalized would resurface on the next tick and the lower third
        # would flicker text/empty forever
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
