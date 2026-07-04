# Translator Lower Third for vMix
# Autore: Michele Dipace <michele.dipace@kaffeine.net>
"""Subtitle text events flowing from provider to formatter (Milestone 5)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TextEventKind(Enum):
    PARTIAL = "partial"
    FINAL = "final"


@dataclass
class TextEvent:
    kind: TextEventKind
    text: str
