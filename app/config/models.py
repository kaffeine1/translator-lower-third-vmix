# Translator Lower Third for vMix
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""Typed configuration models.

Parsing is tolerant by design: a hand-edited or partially corrupt config must
never crash the app. Unknown keys are ignored and invalid values fall back to
their defaults. API keys are intentionally absent from these models — they live
in secure storage (see app/config/secrets.py), never in config.yaml.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _as_int(value: Any, default: int, minimum: int = 0, maximum: int | None = None) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    if result < minimum or (maximum is not None and result > maximum):
        return default
    return result


def _as_str(value: Any, default: str) -> str:
    return value if isinstance(value, str) else default


@dataclass
class AudioConfig:
    device_id: int | str | None = None
    sample_rate: int = 16000
    channels: int = 1

    @classmethod
    def from_dict(cls, data: Any) -> AudioConfig:
        data = _as_dict(data)
        device_id = data.get("device_id")
        if not isinstance(device_id, (int, str)) or isinstance(device_id, bool):
            device_id = None
        return cls(
            device_id=device_id,
            sample_rate=_as_int(data.get("sample_rate"), 16000, minimum=8000),
            channels=_as_int(data.get("channels"), 1, minimum=1, maximum=2),
        )


@dataclass
class VmixConfig:
    host: str = "127.0.0.1"
    port: int = 8088
    input: str = ""
    selected_name: str = "Headline.Text"

    @classmethod
    def from_dict(cls, data: Any) -> VmixConfig:
        data = _as_dict(data)
        return cls(
            host=_as_str(data.get("host"), "127.0.0.1"),
            port=_as_int(data.get("port"), 8088, minimum=1, maximum=65535),
            input=_as_str(data.get("input"), ""),
            selected_name=_as_str(data.get("selected_name"), "Headline.Text"),
        )


@dataclass
class SubtitleConfig:
    max_chars_per_line: int = 42
    max_lines: int = 2
    min_update_interval_ms: int = 1200
    hold_seconds: int = 5
    clear_after_silence_seconds: int = 8

    @classmethod
    def from_dict(cls, data: Any) -> SubtitleConfig:
        data = _as_dict(data)
        return cls(
            max_chars_per_line=_as_int(data.get("max_chars_per_line"), 42, minimum=8),
            max_lines=_as_int(data.get("max_lines"), 2, minimum=1, maximum=4),
            min_update_interval_ms=_as_int(data.get("min_update_interval_ms"), 1200, minimum=0),
            hold_seconds=_as_int(data.get("hold_seconds"), 5, minimum=0),
            clear_after_silence_seconds=_as_int(
                data.get("clear_after_silence_seconds"), 8, minimum=0
            ),
        )


@dataclass
class AppConfig:
    provider: str = "openai"
    source_language: str = "es"
    target_language: str = "it"
    audio: AudioConfig = field(default_factory=AudioConfig)
    vmix: VmixConfig = field(default_factory=VmixConfig)
    subtitles: SubtitleConfig = field(default_factory=SubtitleConfig)

    @classmethod
    def from_dict(cls, data: Any) -> AppConfig:
        data = _as_dict(data)
        return cls(
            provider=_as_str(data.get("provider"), "openai"),
            source_language=_as_str(data.get("source_language"), "es"),
            target_language=_as_str(data.get("target_language"), "it"),
            audio=AudioConfig.from_dict(data.get("audio")),
            vmix=VmixConfig.from_dict(data.get("vmix")),
            subtitles=SubtitleConfig.from_dict(data.get("subtitles")),
        )

    def to_dict(self) -> dict:
        return asdict(self)
