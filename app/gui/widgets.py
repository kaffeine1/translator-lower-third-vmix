# Translator Lower Third for vMix
# Autore: Michele Dipace <michele.dipace@kaffeine.net>
"""Widget riusabili: semaforo di stato, misuratore livello audio, anteprima sottotitolo."""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QProgressBar, QVBoxLayout


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
    StatusState.RED: "Errore",
    StatusState.YELLOW: "Non verificato",
    StatusState.GREEN: "OK",
}


class StatusLight(QLabel):
    """Cerchio colorato rosso/giallo/verde. Parte giallo (non verificato)."""

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
    """Barra di livello audio per il pulsante Test Audio."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setRange(0, 100)
        self.setValue(0)
        self.setTextVisible(False)
        self.setFixedHeight(14)

    def set_level(self, level: float) -> None:
        """level nell'intervallo 0.0–1.0."""
        self.setValue(max(0, min(100, round(level * 100))))


class SubtitlePreview(QFrame):
    """Anteprima dell'ultimo sottotitolo tradotto, su sfondo scuro tipo lower third."""

    PLACEHOLDER = "— nessun sottotitolo —"

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
