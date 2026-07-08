# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""PartialStabilizer / stabilized_callbacks tests (shared anti-flicker logic).

The same append-only stabilization protects the local Faster-Whisper partials
and the volatile cloud interim results (Google, Azure). These tests pin the
append-only guarantee independently of any provider.
"""

from __future__ import annotations

from app.providers._stabilize import PartialStabilizer, stabilized_callbacks


def test_first_hypothesis_commits_nothing():
    # needs two agreeing runs before a word is stable
    stab = PartialStabilizer()
    assert stab.feed("il nostro sistema") == ""


def test_commits_only_agreed_prefix_and_is_append_only():
    stab = PartialStabilizer()
    outs = [
        stab.feed("il nostro sistema"),  # nothing yet
        stab.feed("il nostro sistema cattura"),  # agrees "il nostro sistema"
        stab.feed("il nostro sistema cattura audio"),  # agrees "...cattura"
    ]
    assert outs == ["", "il nostro sistema", "il nostro sistema cattura"]
    # every non-empty emit extends the previous one
    nonempty = [o for o in outs if o]
    for a, b in zip(nonempty, nonempty[1:], strict=False):
        assert b.startswith(a)


def test_never_rewrites_a_shown_word():
    # a word already shown that comes back re-spelled must NOT change on screen
    stab = PartialStabilizer()
    stab.feed("il nostro sistema")
    assert stab.feed("il nostro sistema cattura") == "il nostro sistema"
    revised = stab.feed("il nostro sistemi cattura audio")  # "sistema" -> "sistemi"
    assert "sistemi" not in revised
    assert revised == "il nostro sistema"


def test_agreement_ignores_case_and_edge_punctuation():
    stab = PartialStabilizer()
    stab.feed("Ciao mondo")
    # trailing comma / different case must not read as a revision: both words
    # agree, so both commit (in the second run's spelling)
    assert stab.feed("ciao, mondo bello") == "ciao, mondo"


def test_reset_starts_a_fresh_caption():
    stab = PartialStabilizer()
    stab.feed("uno due")
    stab.feed("uno due tre")
    assert stab._committed  # committed something
    stab.reset()
    assert stab._prev == [] and stab._committed == []
    assert stab.feed("quattro cinque") == ""  # fresh: nothing until it agrees


def test_stabilized_callbacks_are_append_only_and_reset_on_final():
    partials: list[str] = []
    finals: list[str] = []
    on_partial, on_final = stabilized_callbacks(partials.append, finals.append)

    # volatile interim stream: last word keeps changing, earlier words settle
    on_partial("hola")
    on_partial("hola a")  # commit "hola"
    on_partial("hola a todos")  # commit "hola a"
    on_final("hola a todos")  # emits final verbatim + resets

    assert partials == ["hola", "hola a"]  # append-only, no rewrite
    assert finals == ["hola a todos"]

    # after the final the stabilizer is fresh
    on_partial("buenas")
    on_partial("buenas tardes")
    assert partials[-1] == "buenas"


def test_concurrent_feeds_do_not_corrupt_state():
    # cloud SDK callbacks may run on several threads; the lock must keep the
    # wrapper from crashing, deadlocking, or corrupting state under contention
    import threading

    partial, final = stabilized_callbacks(lambda t: None, lambda t: None)
    errors: list[Exception] = []

    def worker(base: str) -> None:
        try:
            for i in range(1, 200):
                partial(f"{base} " + " ".join(str(j) for j in range(i % 10)))
                if i % 25 == 0:
                    final(f"{base} done")
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(b,)) for b in ("a", "b", "c")]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert not errors
