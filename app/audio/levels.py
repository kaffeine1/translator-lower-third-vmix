# Translator Lower Third for vMix
# Autore: Michele Dipace <michele.dipace@kaffeine.net>
"""Calcolo del livello audio per il misuratore del pulsante Test Audio."""

from __future__ import annotations

import numpy as np

_PCM16_FULL_SCALE = 32768.0


def rms_level(chunk: bytes) -> float:
    """Livello RMS 0.0–1.0 di un chunk PCM16 little-endian (mono o interleaved)."""
    samples = np.frombuffer(chunk, dtype=np.int16)
    if samples.size == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(np.square(samples.astype(np.float64)))))
    return min(1.0, rms / _PCM16_FULL_SCALE)


def peak_level(chunk: bytes) -> float:
    """Livello di picco 0.0–1.0 di un chunk PCM16 little-endian."""
    samples = np.frombuffer(chunk, dtype=np.int16)
    if samples.size == 0:
        return 0.0
    return min(1.0, float(np.max(np.abs(samples.astype(np.int32)))) / _PCM16_FULL_SCALE)
