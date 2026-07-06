# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""SubtitleFormatter tests (Milestone 5) — fake clock, no real waiting."""

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
    # live, the most recent words matter: the initial lines are discarded
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


# ---------------------------------------------------------------- finals


def test_final_published_immediately():
    formatter, published, _clock = _formatter()
    formatter.feed_final("Benvenuti alla serata")
    assert published == ["Benvenuti alla serata"]


def test_identical_consecutive_finals_deduplicated():
    formatter, published, _clock = _formatter()
    formatter.feed_final("Ciao a tutti")
    formatter.feed_final("Ciao a tutti")
    formatter.feed_final("  Ciao   a tutti ")  # even after whitespace cleanup
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


# ---------------------------------------------------------------- partials


def test_first_partial_published_immediately():
    # the first words of a caption appear at once (empty -> text is not flicker);
    # this removes the startup lag to the lower third
    formatter, published, clock = _formatter()
    formatter.feed_partial("Hola")
    assert published == ["Hola"]


def test_further_partials_of_same_caption_are_throttled():
    # only the FIRST token is immediate; growth within the caption is throttled
    formatter, published, clock = _formatter()
    formatter.feed_partial("Hola")  # immediate
    formatter.feed_partial("Hola a")  # same caption -> throttled
    clock.advance(0.3)
    formatter.tick()
    assert published == ["Hola"]  # "Hola a" not yet published (interval not elapsed)


def test_partial_published_when_stable():
    formatter, published, clock = _formatter()
    formatter.feed_partial("Hola")  # first token published immediately
    formatter.feed_partial("Hola a todos")  # grows within the caption
    clock.advance(1.3)  # beyond min_update_interval_ms (1200)
    formatter.tick()
    assert published == ["Hola", "Hola a todos"]


def test_growing_partial_published_at_cadence_not_per_word():
    formatter, published, clock = _formatter()
    # phrase that grows every 0.3 s: never stable, but the cadence guarantees
    # about one update per interval
    words = "uno due tre quattro cinque sei sette otto".split()
    text = ""
    for word in words:
        text = f"{text} {word}".strip()
        formatter.feed_partial(text)
        clock.advance(0.3)
        formatter.tick()
    # 8 words in 2.4 s: far fewer updates than words
    assert 1 <= len(published) <= 3


def test_final_clears_pending_partial():
    formatter, published, clock = _formatter()
    formatter.feed_partial("Hola a")  # first token: published immediately
    formatter.feed_final("Hola a todos")
    assert published == ["Hola a", "Hola a todos"]
    # the pending partial must not re-emerge on subsequent ticks
    clock.advance(5)
    formatter.tick()
    assert published == ["Hola a", "Hola a todos"]


def test_new_caption_after_final_published_immediately():
    # inter-phrase latency: once a phrase is finalized, the NEXT phrase's first
    # words appear at once instead of waiting behind the previous caption
    formatter, published, clock = _formatter()
    formatter.feed_final("Prima frase")
    formatter.feed_partial("Seconda")  # pending empty after final -> immediate
    assert published == ["Prima frase", "Seconda"]


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


# ---------------------------------------------------------------- silence


def test_clear_after_silence():
    formatter, published, clock = _formatter()
    formatter.feed_final("Ultima frase")
    clock.advance(8.5)  # beyond clear_after_silence_seconds (8)
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
    clock.advance(6)  # 12 s from the first, but only 6 from the second
    formatter.tick()
    assert "" not in published


def test_hold_prevents_clear_too_soon_after_publish():
    config = SubtitleConfig()
    config.clear_after_silence_seconds = 2
    config.hold_seconds = 5
    formatter, published, clock = _formatter(config)
    formatter.feed_final("Frase breve")
    clock.advance(3)  # silence (>2) but hold not elapsed (<5)
    formatter.tick()
    assert published == ["Frase breve"]
    clock.advance(3)  # now hold is also exceeded
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
    # regression: partial without final (VAD lost, disconnection) →
    # after the silence cleanup it must NOT reappear intermittently
    formatter, published, clock = _formatter()
    formatter.feed_partial("Hola a todos bienvenidos")
    clock.advance(1.3)
    formatter.tick()  # first partial already published immediately
    assert published == ["Hola a todos bienvenidos"]

    clock.advance(8.5)
    formatter.tick()  # silence cleanup
    assert published[-1] == ""

    # simulate 30 seconds of ticks at 250 ms: nothing must reappear
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
    formatter.feed_partial("Qualcosa")  # first token: published immediately
    assert published == ["Qualcosa"]
    formatter.reset()  # reset itself publishes nothing and clears state
    clock.advance(5)
    formatter.tick()
    assert published == ["Qualcosa"]  # nothing new after reset


def test_after_reset_same_text_publishes_again():
    formatter, published, clock = _formatter()
    formatter.feed_final("Ciao")
    formatter.reset()
    formatter.feed_final("Ciao")
    assert published == ["Ciao", "Ciao"]


# ---------------------------------------------------------------- live config update


def test_update_config_rerenders_on_air_text_live():
    # changing max lines/chars while running re-renders the current text at once
    cfg = SubtitleConfig(max_chars_per_line=42, max_lines=2, min_update_interval_ms=0)
    formatter, published, _clock = _formatter(cfg)
    formatter.feed_final("uno due tre quattro cinque sei")
    assert published[-1] == "uno due tre quattro cinque sei"  # one line at 42 chars

    formatter.update_config(
        SubtitleConfig(max_chars_per_line=10, max_lines=1, min_update_interval_ms=0)
    )
    # re-published immediately with the new rules: last 10-char line kept
    assert published[-1] == "cinque sei"


def test_update_config_partials_use_new_rules():
    cfg = SubtitleConfig(max_chars_per_line=42, max_lines=2, min_update_interval_ms=0)
    formatter, published, _clock = _formatter(cfg)
    formatter.update_config(
        SubtitleConfig(max_chars_per_line=8, max_lines=1, min_update_interval_ms=0)
    )
    formatter.feed_partial("alfa beta gamma")
    assert all(len(line) <= 8 for line in published[-1].split("\n"))
