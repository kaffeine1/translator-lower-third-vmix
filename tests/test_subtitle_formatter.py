# Translator Lower Third for vMix
# Autore: Michele Dipace <michele.dipace@kaffeine.net>
"""SubtitleFormatter tests (Milestone 5) — clock finto, nessuna attesa reale."""

from __future__ import annotations

from app.config.models import SubtitleConfig
from app.subtitles.formatter import SubtitleFormatter, clean_text, wrap_lines


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _formatter(config: SubtitleConfig | None = None):
    published: list[str] = []
    clock = FakeClock()
    formatter = SubtitleFormatter(
        config or SubtitleConfig(), published.append, clock=clock
    )
    return formatter, published, clock


# ---------------------------------------------------------------- wrap/clean


def test_wrap_splits_into_max_two_lines():
    text = "Benvenuti a questa serata speciale dedicata alla musica dal vivo"
    lines = wrap_lines(text, max_chars=42, max_lines=2)
    assert len(lines) <= 2
    assert all(len(line) <= 42 for line in lines)


def test_wrap_respects_max_chars_per_line():
    lines = wrap_lines("uno due tre quattro cinque", max_chars=10, max_lines=4)
    assert all(len(line) <= 10 for line in lines)
    assert " ".join(lines) == "uno due tre quattro cinque"


def test_wrap_overflow_keeps_last_lines():
    # in diretta contano le parole più recenti: si scartano le righe iniziali
    text = "inizio vecchio " + "parole nuove importanti finali"
    lines = wrap_lines(text, max_chars=10, max_lines=2)
    assert len(lines) == 2
    assert "finali" in lines[-1]
    assert "inizio" not in " ".join(lines)


def test_wrap_hard_cuts_words_longer_than_line():
    lines = wrap_lines("supercalifragilisti", max_chars=8, max_lines=4)
    assert all(len(line) <= 8 for line in lines)
    assert "".join(lines) == "supercalifragilisti"


def test_clean_text_collapses_whitespace():
    assert clean_text("  Hola   mundo \n") == "Hola mundo"


# ---------------------------------------------------------------- finali


def test_final_published_immediately():
    formatter, published, _clock = _formatter()
    formatter.feed_final("Benvenuti alla serata")
    assert published == ["Benvenuti alla serata"]


def test_identical_consecutive_finals_deduplicated():
    formatter, published, _clock = _formatter()
    formatter.feed_final("Ciao a tutti")
    formatter.feed_final("Ciao a tutti")
    formatter.feed_final("  Ciao   a tutti ")  # anche dopo pulizia spazi
    assert published == ["Ciao a tutti"]


def test_final_is_wrapped_to_two_lines():
    formatter, published, _clock = _formatter()
    formatter.feed_final(
        "Questa è una frase molto lunga che sicuramente non può stare su una sola riga"
    )
    lines = published[-1].split("\n")
    assert len(lines) <= 2
    assert all(len(line) <= 42 for line in lines)


def test_empty_final_ignored():
    formatter, published, _clock = _formatter()
    formatter.feed_final("   ")
    assert published == []


# ---------------------------------------------------------------- parziali


def test_partial_not_published_immediately():
    formatter, published, clock = _formatter()
    formatter.feed_partial("Hola")
    clock.advance(0.3)
    formatter.tick()
    assert published == []


def test_partial_published_when_stable():
    formatter, published, clock = _formatter()
    formatter.feed_partial("Hola a todos")
    clock.advance(1.3)  # oltre min_update_interval_ms (1200)
    formatter.tick()
    assert published == ["Hola a todos"]


def test_growing_partial_published_at_cadence_not_per_word():
    formatter, published, clock = _formatter()
    # frase che cresce ogni 0.3 s: mai stabile, ma la cadenza garantisce
    # un aggiornamento circa ogni intervallo
    words = "uno due tre quattro cinque sei sette otto".split()
    text = ""
    for word in words:
        text = f"{text} {word}".strip()
        formatter.feed_partial(text)
        clock.advance(0.3)
        formatter.tick()
    # 8 parole in 2.4 s: molti meno aggiornamenti delle parole
    assert 1 <= len(published) <= 3


def test_final_clears_pending_partial():
    formatter, published, clock = _formatter()
    formatter.feed_partial("Hola a")
    formatter.feed_final("Hola a todos")
    assert published == ["Hola a todos"]
    # il parziale in sospeso non deve riemergere ai tick successivi
    clock.advance(5)
    formatter.tick()
    assert published == ["Hola a todos"]


def test_partial_identical_to_published_not_repeated():
    formatter, published, clock = _formatter()
    formatter.feed_final("Hola a todos")
    formatter.feed_partial("Hola a todos")
    clock.advance(2)
    formatter.tick()
    assert published == ["Hola a todos"]


def test_empty_partial_ignored():
    formatter, published, clock = _formatter()
    formatter.feed_partial("")
    clock.advance(2)
    formatter.tick()
    assert published == []


# ---------------------------------------------------------------- silenzio


def test_clear_after_silence():
    formatter, published, clock = _formatter()
    formatter.feed_final("Ultima frase")
    clock.advance(8.5)  # oltre clear_after_silence_seconds (8)
    formatter.tick()
    assert published == ["Ultima frase", ""]


def test_no_clear_before_silence_timeout():
    formatter, published, clock = _formatter()
    formatter.feed_final("Frase")
    clock.advance(7.0)
    formatter.tick()
    assert published == ["Frase"]


def test_new_text_resets_silence_timer():
    formatter, published, clock = _formatter()
    formatter.feed_final("Prima")
    clock.advance(6)
    formatter.feed_final("Seconda")
    clock.advance(6)  # 12 s dalla prima, ma solo 6 dalla seconda
    formatter.tick()
    assert "" not in published


def test_hold_prevents_clear_too_soon_after_publish():
    config = SubtitleConfig()
    config.clear_after_silence_seconds = 2
    config.hold_seconds = 5
    formatter, published, clock = _formatter(config)
    formatter.feed_final("Frase breve")
    clock.advance(3)  # silenzio (>2) ma hold non trascorso (<5)
    formatter.tick()
    assert published == ["Frase breve"]
    clock.advance(3)  # ora anche hold superato
    formatter.tick()
    assert published == ["Frase breve", ""]


def test_clear_disabled_when_zero():
    config = SubtitleConfig()
    config.clear_after_silence_seconds = 0
    formatter, published, clock = _formatter(config)
    formatter.feed_final("Testo")
    clock.advance(60)
    formatter.tick()
    assert published == ["Testo"]


def test_clear_not_repeated():
    formatter, published, clock = _formatter()
    formatter.feed_final("Frase")
    clock.advance(9)
    formatter.tick()
    clock.advance(9)
    formatter.tick()
    assert published == ["Frase", ""]


def test_unfinalized_partial_does_not_resurrect_after_silence_clear():
    # regressione: parziale senza finale (VAD perso, disconnessione) →
    # dopo la pulizia per silenzio NON deve riapparire a intermittenza
    formatter, published, clock = _formatter()
    formatter.feed_partial("Hola a todos bienvenidos")
    clock.advance(1.3)
    formatter.tick()  # pubblicato come parziale stabile
    assert published == ["Hola a todos bienvenidos"]

    clock.advance(8.5)
    formatter.tick()  # pulizia per silenzio
    assert published[-1] == ""

    # simula 30 secondi di tick a 250 ms: niente deve riapparire
    for _ in range(120):
        clock.advance(0.25)
        formatter.tick()
    assert published == ["Hola a todos bienvenidos", ""]


def test_publish_resumes_after_clear():
    formatter, published, clock = _formatter()
    formatter.feed_final("Prima")
    clock.advance(9)
    formatter.tick()
    formatter.feed_final("Seconda")
    assert published == ["Prima", "", "Seconda"]


# ---------------------------------------------------------------- reset


def test_reset_clears_state_without_publishing():
    formatter, published, clock = _formatter()
    formatter.feed_partial("Qualcosa")
    formatter.reset()
    clock.advance(5)
    formatter.tick()
    assert published == []


def test_after_reset_same_text_publishes_again():
    formatter, published, clock = _formatter()
    formatter.feed_final("Ciao")
    formatter.reset()
    formatter.feed_final("Ciao")
    assert published == ["Ciao", "Ciao"]
