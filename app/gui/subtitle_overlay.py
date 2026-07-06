# Traduttore Live
# Author: Michele Dipace <michele.dipace@kaffeine.net>
"""On-screen subtitle overlay.

A frameless, always-on-top, click-through translucent window that shows the
current subtitle as a bottom-centered caption (white text on a semi-transparent
grey box) on a chosen monitor. It is a pure display surface: it holds no
pipeline/provider logic and is fed text by the GUI, exactly like the vMix output
is fed by the pipeline.

Multi-monitor: ``available_monitors()`` lists the connected screens for the
settings dropdown; the overlay is placed on the screen whose QScreen.name()
matches the saved value (empty = primary), with a safe fallback to the primary
screen when the saved monitor is gone.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QScreen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

# never shrink the auto-fit font below this (readability floor)
_MIN_FONT_POINT_SIZE = 10

# Grey caption background; only the alpha (opacity) is user-configurable.
_BACKGROUND_RGB = (30, 30, 30)


@dataclass(frozen=True)
class MonitorInfo:
    """A connected screen, for the settings dropdown."""

    name: str  # QScreen.name(), the stable identifier stored in config
    index: int
    width: int
    height: int
    primary: bool


def available_monitors() -> list[MonitorInfo]:
    """The connected screens, in QGuiApplication order."""
    primary = QGuiApplication.primaryScreen()
    monitors: list[MonitorInfo] = []
    for index, screen in enumerate(QGuiApplication.screens()):
        try:
            geometry = screen.geometry()
        except RuntimeError:
            # the C++ QScreen was deleted mid-enumeration (a display-layout
            # change): skip it rather than dereference a dead object
            continue
        monitors.append(
            MonitorInfo(
                name=screen.name(),
                index=index,
                width=geometry.width(),
                height=geometry.height(),
                primary=screen is primary,
            )
        )
    return monitors


def screen_by_name(name: str) -> QScreen | None:
    """The screen with the given name, or the primary screen as a fallback."""
    if name:
        for screen in QGuiApplication.screens():
            if screen.name() == name:
                return screen
    return QGuiApplication.primaryScreen()


def _live_screen(screen: QScreen | None) -> QScreen | None:
    """Return ``screen`` only if it is still a connected screen, else the primary.

    A QScreen the app holds can be deleted by Qt when the display layout
    changes (a monitor unplugged, a resolution change, sleep/wake). Calling
    ``geometry()`` on the stale wrapper then crashes natively inside
    ``QScreen::geometry`` (Qt6Gui access violation). Re-validating against the
    live screen list before using it avoids dereferencing a dead screen.
    """
    try:
        if screen is not None and screen in QGuiApplication.screens():
            return screen
    except RuntimeError:
        pass
    return QGuiApplication.primaryScreen()


class SubtitleOverlay(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        # a parent keeps ownership (destroyed with the main window), while the
        # window flags below still make it an independent top-level surface that
        # can live on any monitor.
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        # translucent so only the caption box paints; click-through so it never
        # steals input from whatever runs on that monitor.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(48, 24, 48, 64)  # keep the caption off the edges
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        self._label = QLabel("", self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # NO word wrap: honor the formatter's exact line count (max_lines); a
        # line too wide for the screen is handled by shrinking the font, not by
        # wrapping onto extra lines.
        self._label.setWordWrap(False)
        self._label.setVisible(False)  # no empty grey box when there is no text
        row.addWidget(self._label)
        row.addStretch(1)
        outer.addLayout(row)

        self._font_point_size = 32  # the configured (maximum) size
        self._current_font_size = 32  # after auto-fit
        self._background_opacity = 160
        self._max_width = 0  # available caption width (set in show_on)
        self._apply_style()

    # ------------------------------------------------------------------ API

    def set_text(self, text: str) -> None:
        text = (text or "").strip()
        self._label.setText(text)
        self._label.setVisible(bool(text))
        if text:
            self._fit_font()

    def apply_config(self, *, font_point_size: int, background_opacity: int) -> None:
        self._font_point_size = max(int(font_point_size), 8)
        self._current_font_size = self._font_point_size
        self._background_opacity = min(max(int(background_opacity), 0), 255)
        self._apply_style()
        self._fit_font()

    def show_on(self, screen: QScreen | None) -> None:
        # re-validate against the live screen list: a stale QScreen would crash
        # natively in QScreen::geometry() on a display-layout change
        screen = _live_screen(screen)
        if screen is not None:
            try:
                geometry = screen.geometry()
            except RuntimeError:
                geometry = None  # C++ QScreen deleted between the check and here
            if geometry is not None and not geometry.isNull():
                self.setGeometry(geometry)
                self._max_width = int(geometry.width() * 0.92)
        self.show()
        self.raise_()
        self._fit_font()

    # ------------------------------------------------------------------ internal

    def _apply_style(self) -> None:
        # colours/box only; the font (size + bold) is a QFont so sizeHint()
        # reflects it and the auto-fit below is accurate.
        r, g, b = _BACKGROUND_RGB
        self._label.setStyleSheet(
            "QLabel {"
            " color: white;"
            f" background-color: rgba({r}, {g}, {b}, {self._background_opacity});"
            " padding: 10px 24px;"
            " border-radius: 10px;"
            " }"
        )
        self._set_font(self._current_font_size)

    def _set_font(self, point_size: int) -> None:
        font = self._label.font()
        font.setPointSize(max(int(point_size), _MIN_FONT_POINT_SIZE))
        font.setBold(True)
        self._label.setFont(font)

    def _fit_font(self) -> None:
        """Shrink the font (from the configured size) so the widest line fits the
        screen — honoring max_lines instead of wrapping onto extra lines."""
        if self._max_width <= 0 or not self._label.isVisible():
            self._current_font_size = self._font_point_size
            self._set_font(self._current_font_size)
            return
        size = self._font_point_size
        self._current_font_size = size
        self._set_font(size)
        while size > _MIN_FONT_POINT_SIZE and self._label.sizeHint().width() > self._max_width:
            size -= 2
            self._current_font_size = size
            self._set_font(size)
