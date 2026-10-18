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
    candles  : Candle 객체 리스트 (t, o, h, l, c, v 속성 필요)
    x_offset : 캔들 인덱스 시작 위치 (live bar 오버레이에 사용)
               기본값 0 → 인덱스 0부터 시작
               len(closed_candles) 전달 시 닫힌 봉 바로 다음 위치에 그림
    """

    def __init__(
        self,
        candles: list,
        up_color: str = "#26A69A",
        dn_color: str = "#EF5350",
        x_offset: int = 0,
    ) -> None:
        super().__init__()
        self._candles  = candles
        self._up_color = up_color
        self._dn_color = dn_color
        self._x_offset = x_offset
        self._picture: QPicture | None = None
        self._generate()

    def set_candles(self, candles: list, x_offset: int = 0) -> None:
        self._candles  = candles
        self._x_offset = x_offset
        self._picture  = None
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
            x = i + self._x_offset          # 실제 x 좌표
            color = self._up_color if c.c >= c.o else self._dn_color
            pen   = pg.mkPen(color, width=1)
            brush = pg.mkBrush(color)
            p.setPen(pen)
            p.setBrush(brush)

            body_top = max(c.o, c.c)
            body_bot = min(c.o, c.c)
            body_h   = max(body_top - body_bot, 0.001)

            # 심지 먼저 — body가 위에 덮어씌워야 경계선이 자연스러움
            # 실제로 연장될 때만 그림 (zero-length 선 → 픽셀 잡음 방지)
            if c.l < body_bot:
                p.drawLine(QLineF(x, c.l, x, body_bot))
            if c.h > body_top:
                p.drawLine(QLineF(x, body_top, x, c.h))

            # 몸통 (심지 위에 덮어씌움)
            p.drawRect(QRectF(x - w, body_bot, w * 2, body_h))
        p.end()

    def paint(self, p, *args) -> None:
        if self._picture:
            p.drawPicture(0, 0, self._picture)

    def boundingRect(self) -> QRectF:
        if self._picture:
            r = self._picture.boundingRect()
            return QRectF(r.x(), r.y(), r.width(), r.height())
        return QRectF()
