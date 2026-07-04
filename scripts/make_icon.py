# Translator Lower Third for vMix
# Autore: Michele Dipace <michele.dipace@kaffeine.net>
"""Genera assets/icon.ico usando PySide6 (nessuna dipendenza esterna).

Icona semplice: sfondo scuro arrotondato (come un lower third) con due barre di
sottotitolo (bianca + verde). Rigenerabile con:

    python scripts/make_icon.py
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QGuiApplication, QImage, QPainter

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "icon.ico"
SIZE = 256


def render(size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # sfondo arrotondato scuro
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(QColor("#222831")))
    painter.drawRoundedRect(QRectF(8, 8, size - 16, size - 16), 36, 36)

    # barra sottotitolo bianca (riga 1) e verde (riga 2)
    margin = size * 0.18
    bar_h = size * 0.13
    width = size - 2 * margin
    painter.setBrush(QBrush(QColor("#f2f2f2")))
    painter.drawRoundedRect(
        QRectF(margin, size * 0.40, width, bar_h), 10, 10
    )
    painter.setBrush(QBrush(QColor("#5cb85c")))
    painter.drawRoundedRect(
        QRectF(margin, size * 0.58, width * 0.7, bar_h), 10, 10
    )
    painter.end()
    return image


def main() -> None:
    app = QGuiApplication.instance() or QGuiApplication([])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    image = render(SIZE)
    if not image.save(str(OUT), "ICO"):
        raise SystemExit("Salvataggio icona fallito")
    print(f"Icona creata: {OUT}")
    del app


if __name__ == "__main__":
    main()
