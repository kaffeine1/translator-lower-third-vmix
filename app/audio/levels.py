# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""Audio level computation for the Test Audio button meter."""

from __future__ import annotations

import numpy as np

_PCM16_FULL_SCALE = 32768.0


def rms_level(chunk: bytes) -> float:
    """RMS level 0.0–1.0 of a little-endian PCM16 chunk (mono or interleaved)."""
    samples = np.frombuffer(chunk, dtype=np.int16)
    if samples.size == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(np.square(samples.astype(np.float64)))))
    return min(1.0, rms / _PCM16_FULL_SCALE)


def peak_level(chunk: bytes) -> float:
    """Peak level 0.0–1.0 of a little-endian PCM16 chunk."""
    samples = np.frombuffer(chunk, dtype=np.int16)
    if samples.size == 0:
        return 0.0
    return min(1.0, float(np.max(np.abs(samples.astype(np.int32)))) / _PCM16_FULL_SCALE)
