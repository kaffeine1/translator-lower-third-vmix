# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""Reusable widgets: status light, audio level meter, subtitle preview."""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QProgressBar, QVBoxLayout

from app.i18n import t


class StatusState(Enum):
    RED = "rosso"
    YELLOW = "giallo"
    GREEN = "verde"


_STATE_COLORS = {
    StatusState.RED: "#d9534f",
    StatusState.YELLOW: "#f0ad4e",
    StatusState.GREEN: "#5cb85c",
}

_STATE_TOOLTIPS = {
    StatusState.RED: t("widgets.status.error"),
    StatusState.YELLOW: t("widgets.status.unverified"),
    StatusState.GREEN: t("widgets.status.ok"),
}


class StatusLight(QLabel):
    """Colored red/yellow/green circle. Starts yellow (not verified)."""

    DIAMETER = 18

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(self.DIAMETER, self.DIAMETER)
        self._state = StatusState.YELLOW
        self.set_state(StatusState.YELLOW)

    @property
    def state(self) -> StatusState:
        return self._state

    def set_state(self, state: StatusState) -> None:
        self._state = state
        radius = self.DIAMETER // 2
        self.setStyleSheet(
            f"background-color: {_STATE_COLORS[state]};"
            f" border-radius: {radius}px; border: 1px solid #666;"
        )
        self.setToolTip(_STATE_TOOLTIPS[state])


class AudioLevelMeter(QProgressBar):
    """Audio level bar for the Test Audio button."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setRange(0, 100)
        self.setValue(0)
        self.setTextVisible(False)
        self.setFixedHeight(14)

    def set_level(self, level: float) -> None:
        """level in the 0.0–1.0 range."""
        self.setValue(max(0, min(100, round(level * 100))))


class SubtitlePreview(QFrame):
    """Preview of the last translated subtitle, on a dark lower-third-style background."""

    PLACEHOLDER = t("widgets.subtitle.placeholder")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("subtitle_preview")
        self.setStyleSheet(
            "#subtitle_preview { background-color: #222; border-radius: 4px; }"
        )
        self.setMinimumHeight(72)
        self._text = ""
        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setWordWrap(True)
        self._label.setStyleSheet("color: white; font-size: 16px; padding: 8px;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self._label)
        self.set_text("")

    def set_text(self, text: str) -> None:
        self._text = text
        self._label.setText(text if text else self.PLACEHOLDER)

    def text(self) -> str:
        return self._text
