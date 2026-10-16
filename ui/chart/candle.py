# ui/chart/candle.py
# CandlestickItem — pyqtgraph (PyQt6 호환)
# Tradier_Working2/ui/minute_chart/chart_candle.py 기반, PyQt5 → PyQt6 변환

from __future__ import annotations
import pyqtgraph as pg
from PyQt6.QtCore import QRectF, QLineF
from PyQt6.QtGui  import QPicture, QPainter


class CandlestickItem(pg.GraphicsObject):
    """
    pyqtgraph 캔들스틱 아이템.
    candles: Candle 객체 리스트 (t, o, h, l, c, v 속성 필요)
    """

    def __init__(
        self,
        candles: list,
        up_color: str = "#26A69A",
        dn_color: str = "#EF5350",
    ) -> None:
        super().__init__()
        self._candles  = candles
        self._up_color = up_color
        self._dn_color = dn_color
        self._picture: QPicture | None = None
        self._generate()

    def set_candles(self, candles: list) -> None:
        self._candles = candles
        self._picture = None
        self._generate()
        self.update()

    def set_colors(self, up: str, dn: str) -> None:
        self._up_color = up
        self._dn_color = dn
        self._picture  = None
        self._generate()
        self.update()

    def _generate(self) -> None:
        self._picture = QPicture()
        p = QPainter(self._picture)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        w = 0.4
        for i, c in enumerate(self._candles):
            color = self._up_color if c.c >= c.o else self._dn_color
            pen   = pg.mkPen(color, width=1)
            brush = pg.mkBrush(color)
            p.setPen(pen)
            p.setBrush(brush)
            # 몸통
            body_top = max(c.o, c.c)
            body_bot = min(c.o, c.c)
            body_h   = max(body_top - body_bot, 0.001)
            p.drawRect(QRectF(i - w, body_bot, w * 2, body_h))
            # 심지
            p.drawLine(QLineF(i, c.l, i, body_bot))
            p.drawLine(QLineF(i, body_top, i, c.h))
        p.end()

    def paint(self, p, *args) -> None:
        if self._picture:
            p.drawPicture(0, 0, self._picture)

    def boundingRect(self) -> QRectF:
        if self._picture:
            r = self._picture.boundingRect()
            return QRectF(r.x(), r.y(), r.width(), r.height())
        return QRectF()
