# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""Append-only stabilization of streaming speech partials (LocalAgreement-2).

Streaming recognizers revise their guess between ticks: a word already shown on
screen can come back spelled differently — local re-transcription of a growing
buffer, Google interim results, Azure "recognizing" hypotheses all do this.
Emitting the latest guess verbatim makes the caption flicker: words rewrite
themselves in front of the operator. This keeps a frozen, append-only prefix —
only the word-prefix that two consecutive guesses agree on is committed, and a
committed word is never rewritten. The still-unstable tail is withheld until it
settles.

Safe ONLY for monolingual recognition of the same growing audio, where the
hypotheses converge on the same words. Do NOT run it on machine-translated
text: translating a longer source prefix legitimately reorders earlier words,
so freezing them would be wrong (that is why the ComposedRealtimeProvider does
not stabilize the translated output — only the source/STT layer does).
"""

from __future__ import annotations

import threading
from collections.abc import Callable


def _norm(word: str) -> str:
    """Compare words ignoring case and edge punctuation, so a word that gains a
    trailing comma between ticks is not mistaken for a revision."""
    return word.lower().strip(".,;:!?¿¡\"'()").strip()


class PartialStabilizer:
    """Feed each new full hypothesis, get back the stable text to show; call
    reset() at each final so a closed caption starts fresh."""

    def __init__(self) -> None:
        self._prev: list[str] = []  # words of the previous hypothesis (agreement)
        self._committed: list[str] = []  # frozen, append-only words already shown

    def feed(self, text: str) -> str:
        words = text.split()
        # LocalAgreement-2: the stable prefix is what this guess and the last
        # one agree on, word for word.
        agreed = 0
        for a, b in zip(self._prev, words, strict=False):
            if _norm(a) == _norm(b):
                agreed += 1
            else:
                break
        self._prev = words
        stable = words[:agreed]
        # Freeze by VALUE, not by count: extend only where this guess still
        # agrees with what is already shown, so a committed word is never
        # rewritten — the visible text is strictly append-only.
        c = len(self._committed)
        already = [_norm(w) for w in self._committed]
        if [_norm(w) for w in stable[:c]] == already and agreed > c:
            self._committed.extend(words[c:agreed])
        return " ".join(self._committed)

    def reset(self) -> None:
        self._prev = []
        self._committed = []


TextCb = Callable[[str], None]


def stabilized_callbacks(on_partial: TextCb, on_final: TextCb) -> tuple[TextCb, TextCb]:
    """Wrap a provider's (on_partial, on_final) so partials are append-only
    stabilized and the stabilizer resets on each final. A fresh stabilizer is
    created per call, so wire it once per connect().

    The lock both guards the stabilizer state AND serializes DELIVERY: cloud SDK
    callbacks may arrive on several threads, so if a "recognizing" and a
    "recognized" ran concurrently, delivering a partial that was decided before
    a final AFTER that final would show a stale, backwards caption. Emitting
    under the lock keeps deliveries in a well-defined order — a partial decided
    before a final is delivered before it (and the downstream seq guard then
    invalidates it). This is safe because the consumers in this pipeline are
    non-blocking and never re-enter here: the ComposedRealtimeProvider hands the
    text off to the asyncio loop (run_coroutine_threadsafe) or does a quick
    in-memory update, so holding the lock across the call cannot deadlock the
    recognizer. Callbacks passed here MUST keep that contract (no blocking work,
    no re-entry into these wrappers)."""
    stab = PartialStabilizer()
    lock = threading.Lock()
    last = ""  # last committed text emitted (skip identical re-emits)

    def partial(text: str) -> None:
        nonlocal last
        with lock:
            committed = stab.feed(text)
            # withhold until a word is stable, and skip an unchanged prefix (a
            # tick can add no new committed word) so no redundant re-translation
            # is triggered downstream
            if committed and committed != last:
                last = committed
                on_partial(committed)

    def final(text: str) -> None:
        nonlocal last
        with lock:
            stab.reset()
            last = ""
            on_final(text)

    return partial, final
