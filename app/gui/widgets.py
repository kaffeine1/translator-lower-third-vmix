# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""Reusable widgets: status light, audio level meter, subtitle preview."""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QAbstractSlider,
    QAbstractSpinBox,
    QComboBox,
    QFrame,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from app.i18n import t


class _WheelGuard(QObject):
    """Event filter that keeps the mouse wheel from changing a form field.

    Over a spin box, combo box or slider Qt changes the value with the wheel.
    In a scrolling settings form, the fields slide under the pointer while the
    operator scrolls the page, and their values change unnoticed: that is how
    the vMix port went 8088 → 8089 and 8088 → 8087 at two live shows. The
    wheel event is ignored by the field and Qt passes it on to the parents, so
    the page scrolls instead; a value changes only by clicking, typing or with
    the arrow keys.
    """

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt name)
        if event.type() == QEvent.Type.Wheel:
            event.ignore()  # not accepted: Qt propagates it to the parent widgets
            return True  # never delivered to the field itself
        return False


def disable_wheel_on_fields(root: QWidget) -> None:
    """Make the mouse wheel scroll the page instead of changing the value of
    any spin box, combo box or slider inside ``root`` (see _WheelGuard).

    Safe to call again after adding fields: a widget keeps a single guard."""
    guard = root.findChild(_WheelGuard)
    if guard is None:
        guard = _WheelGuard(root)
    for kind in (QAbstractSpinBox, QComboBox, QAbstractSlider):
        for field in root.findChildren(kind):
            # no focus grab by the wheel either (the default for these fields)
            field.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            field.installEventFilter(guard)


def credential_help_label(cred) -> QLabel | None:
    """A small, muted help line to show under a credential field: a one-line
    "how to obtain this" hint and a link that opens the provider's console page
    in the browser. Returns None when the credential declares no help.

    ``cred`` is a registry.CredentialField (duck-typed: needs help_key/help_url).
    The link opens externally (QLabel.setOpenExternalLinks), so no wiring is
    needed at the call site.
    """
    hint = t(cred.help_key) if getattr(cred, "help_key", "") else ""
    url = getattr(cred, "help_url", "")
    if url:
        link = f'<a href="{url}">{t("cred.get_key_link")}</a>'
        hint = f"{hint} {link}".strip()
    if not hint:
        return None
    label = QLabel(hint)
    label.setObjectName("cred_help")
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setOpenExternalLinks(True)
    label.setWordWrap(True)
    # muted but READABLE in both light and dark themes: use the palette's
    # PlaceholderText role (the same secondary-text grey as field placeholders) —
    # NOT a fixed grey or the Mid role, which is a border/shadow tone too dark to
    # read on a dark background. The link keeps its own (Link) colour.
    palette = label.palette()
    palette.setColor(
        QPalette.ColorRole.WindowText,
        palette.color(QPalette.ColorRole.PlaceholderText),
    )
    label.setPalette(palette)
    font = label.font()
    if font.pointSize() > 0:
        font.setPointSize(font.pointSize() - 1)  # secondary text: slightly smaller
    label.setFont(font)
    return label


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
