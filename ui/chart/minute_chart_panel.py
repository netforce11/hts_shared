# ui/chart/minute_chart_panel.py
# 분봉 차트 패널 — PyQt6, hts_shared BasePanel 상속
# Tradier_Working2/ui/minute_chart/minute_chart_panel.py 기반 재작성
#
# 각 프로젝트에서 사용법:
#   class MyChartPanel(MinuteChartPanel):
#       def _make_minute_loader(self, symbol, date):
#           return MyIBKRMinuteLoader(symbol, date)
#       def _make_daily_loader(self, symbol, days):
#           return MyDailyLoader(symbol, days)

from __future__ import annotations
from datetime  import date, datetime, timezone, timedelta

from PyQt6.QtWidgets import (
    QHBoxLayout, QVBoxLayout, QSplitter,
    QWidget, QLabel, QPushButton, QComboBox,
)
from PyQt6.QtCore import Qt, QDate, pyqtSlot
from PyQt6.QtGui  import QFont

from ..panels.base_panel import BasePanel
from ...core.bus import DataBus
from ...core.topics import Topics


class MinuteChartPanel(BasePanel):
    """
    공통 분봉 차트 패널.
    데이터 로딩은 _make_minute_loader / _make_daily_loader 오버라이드로 주입.
    """
    PANEL_ID = "minute_chart"

    # 캔들 색상 (서브클래스에서 오버라이드 가능)
    UP_COLOR = "#26A69A"
    DN_COLOR = "#EF5350"

    def __init__(self, bus: DataBus, parent=None) -> None:
        super().__init__(bus, parent)
        self._symbol   = "AAPL"
        self._candles  = []
        self._loader   = None
        self._live_bar = None
        self._build_body()

        # DataBus 구독
        bus.subscribe(Topics.SYSTEM_STATUS, self,
                      lambda d: self._invoke_main("_on_status_msg", d))

    # ── 레이아웃 ─────────────────────────────────────────────
    def _build_body(self) -> None:
        from PyQt6.QtWidgets import QCalendarWidget
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_sidebar())
        splitter.addWidget(self._build_chart_area())
        splitter.setSizes([220, 900])
        splitter.setHandleWidth(4)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self._layout.addWidget(splitter)

        self._status_lbl = QLabel("대기 중...")
        self._layout.addWidget(self._status_lbl)

    def _build_sidebar(self) -> QWidget:
        from PyQt6.QtWidgets import QCalendarWidget
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)

        # 심볼 입력
        self._sym_input = QComboBox()
        self._sym_input.setEditable(True)
        self._sym_input.addItems(["AAPL", "SPY", "QQQ", "TSLA", "NVDA"])
        self._sym_input.setCurrentText(self._symbol)
        self._sym_input.lineEdit().returnPressed.connect(self._on_symbol_enter)
        lay.addWidget(QLabel("심볼"))
        lay.addWidget(self._sym_input)

        # 캘린더
        lay.addWidget(QLabel("날짜"))
        self._calendar = QCalendarWidget()
        self._calendar.setMaximumDate(QDate.currentDate())
        self._calendar.setSelectedDate(QDate.currentDate())
        self._calendar.selectionChanged.connect(self._on_date_changed)
        self._calendar.setFixedHeight(180)
        lay.addWidget(self._calendar)

        # 이전/다음 버튼
        nav = QHBoxLayout()
        btn_prev = QPushButton("◀ 전날")
        btn_next = QPushButton("다음 ▶")
        btn_prev.clicked.connect(self._go_prev_day)
        btn_next.clicked.connect(self._go_next_day)
        nav.addWidget(btn_prev)
        nav.addWidget(btn_next)
        lay.addLayout(nav)

        lay.addStretch()
        return w

    def _build_chart_area(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        try:
            import pyqtgraph as pg
            pg.setConfigOptions(antialias=False, useOpenGL=False)

            self._gfx = pg.GraphicsLayoutWidget()
            # 키움 스타일: 연분홍~흰색 라이트 배경
            self._gfx.setBackground("#FFF5F7")

            # p1 — 캔들
            self._p1 = self._gfx.addPlot(row=0, col=0)
            self._p1.showGrid(x=True, y=True, alpha=0.15)  # 라이트 배경 → 격자 연하게
            self._p1.setLabel("left", "가격")
            self._p1.setMenuEnabled(False)

            # p2 — 거래량
            self._gfx.nextRow()
            self._p2 = self._gfx.addPlot(row=1, col=0)
            self._p2.setXLink(self._p1)
            self._p2.setMaximumHeight(80)
            self._p2.setLabel("left", "거래량")
            self._p2.setMenuEnabled(False)
            self._p2.hideAxis("bottom")

            # ── GraphicsLayoutWidget 내부 행 비율 설정 ──────────
            # 미설정 시 하단에 빈 공간이 남음 (tradier_working2 참고)
            self._gfx.ci.layout.setRowStretchFactor(0, 4)   # 캔들: 4배 확장
            self._gfx.ci.layout.setRowMinimumHeight(0, 150) # 캔들 최소 높이
            self._gfx.ci.layout.setRowMaximumHeight(1, 80)  # 거래량 최대 80px
            self._gfx.ci.layout.setRowStretchFactor(1, 1)   # 거래량: 1배

            lay.addWidget(self._gfx, 1)   # stretch=1: 수직 공간 채우기
            # 초기 라이트 테마 적용 (키움 스타일)
            self.apply_theme()
        except Exception as e:
            lay.addWidget(QLabel(f"pyqtgraph 오류: {e}"))
        return w

    # ── 단축키 선언 ───────────────────────────────────────────
    def register_shortcuts(self) -> list:
        # super() 호출 필수: BasePanel의 Alt+=/- (패널 크기), Alt+]/[ (폰트) 포함
        return super().register_shortcuts() + [
            ("Left",  self._go_prev_day),
            ("Right", self._go_next_day),
            ("F5",    self._refresh),
        ]

    # ── 데이터 로더 주입 (서브클래스에서 오버라이드) ──────────
    def _make_minute_loader(self, symbol: str, target_date: date):
        """각 프로젝트에서 반드시 오버라이드"""
        raise NotImplementedError("_make_minute_loader를 오버라이드하세요")

    def _make_daily_loader(self, symbol: str, days: int = 60):
        raise NotImplementedError("_make_daily_loader를 오버라이드하세요")

    # ── 사이드바 이벤트 ───────────────────────────────────────
    def _on_symbol_enter(self) -> None:
        sym = self._sym_input.currentText().strip().upper()
        if sym:
            self._set_symbol(sym)

    def _on_date_changed(self) -> None:
        d = self._calendar.selectedDate().toPyDate()
        self._load_minute(d)

    def _go_prev_day(self) -> None:
        d = self._calendar.selectedDate().toPyDate() - timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        self._calendar.setSelectedDate(QDate(d.year, d.month, d.day))

    def _go_next_day(self) -> None:
        d = self._calendar.selectedDate().toPyDate() + timedelta(days=1)
        while d.weekday() >= 5:
            d += timedelta(days=1)
        if d > date.today():
            d = date.today()
        self._calendar.setSelectedDate(QDate(d.year, d.month, d.day))

    def _refresh(self) -> None:
        d = self._calendar.selectedDate().toPyDate()
        self._load_minute(d)

    def _set_symbol(self, symbol: str) -> None:
        self._symbol = symbol.upper()
        self._sym_input.setCurrentText(self._symbol)
        self._candles = []
        self._clear_chart()
        d = self._calendar.selectedDate().toPyDate()
        self._load_minute(d)

    # ── 데이터 로드 ───────────────────────────────────────────
    def _load_minute(self, d: date) -> None:
        if self._loader and self._loader.isRunning():
            self._loader.terminate()
            self._loader.wait(500)
        self._set_status(f"⏳ {d} 로딩 중...")
        self._candles = []
        try:
            self._loader = self._make_minute_loader(self._symbol, d)
            self._loader.loaded.connect(self._on_minute_loaded)
            self._loader.error.connect(self._on_load_error)
            self._loader.start()
        except NotImplementedError:
            self._set_status("❌ _make_minute_loader 미구현")

    def _on_minute_loaded(self, candles: list) -> None:
        self._candles = candles
        is_today = (self._calendar.selectedDate().toPyDate() == date.today())
        suffix = " | 📡 실시간" if is_today else ""
        self._set_status(f"✅ {len(candles)}봉 로드{suffix}")
        self._render()

    def _on_load_error(self, msg: str) -> None:
        self._set_status(f"❌ {msg}")

    # ── 렌더링 ────────────────────────────────────────────────
    def _render(self) -> None:
        if not hasattr(self, "_p1") or not self._candles:
            return
        try:
            import pyqtgraph as pg
            from .candle import CandlestickItem

            self._p1.clear()
            self._p2.clear()

            # ── 유효한 캔들만 필터 (IBKR에서 -1 / 0 값 오는 경우 제거) ──
            valid = [c for c in self._candles
                     if c.h > 0 and c.l > 0 and c.o > 0 and c.c > 0
                     and c.h >= c.l and c.h >= c.o and c.h >= c.c]
            if not valid:
                self._set_status("표시할 유효 캔들 없음")
                return

            # 캔들스틱
            item = CandlestickItem(valid, self.UP_COLOR, self.DN_COLOR)
            self._p1.addItem(item)

            # 거래량 바
            xs     = list(range(len(valid)))
            vs     = [max(c.v, 0) for c in valid]   # 음수 volume(-1) 보호
            colors = [self.UP_COLOR if c.c >= c.o else self.DN_COLOR
                      for c in valid]
            bars = pg.BarGraphItem(
                x=xs, height=vs, width=0.6,
                brushes=colors, pens=colors)
            self._p2.addItem(bars)

            # ── 명시적 Y/X 범위 (auto-range 오차 방지) ──────────────
            lows  = [c.l for c in valid]
            highs = [c.h for c in valid]
            y_min, y_max = min(lows), max(highs)
            span  = max(y_max - y_min, y_max * 0.001)
            pad   = span * 0.05
            self._p1.setYRange(y_min - pad, y_max + pad, padding=0)
            self._p1.setXRange(-1, len(valid) + 1, padding=0)

            if vs:
                self._p2.setYRange(0, max(vs) * 1.1, padding=0)
                self._p2.setXRange(-1, len(valid) + 1, padding=0)

            # x축 시간 레이블
            ticks = {}
            step = max(1, len(valid) // 10)
            for i in range(0, len(valid), step):
                ticks[i] = datetime.fromtimestamp(
                    valid[i].t).strftime("%H:%M")
            self._p1.getAxis("bottom").setTicks([list(ticks.items())])

        except Exception as e:
            self._set_status(f"렌더 오류: {e}")

    # ── 실시간 DataBus 토픽 ───────────────────────────────────
    def on_candle_tick(self, data: dict) -> None:
        """프로젝트에서 DataBus 구독 후 호출"""
        if data.get("symbol", "").upper() != self._symbol:
            return
        self._live_bar = data
        if self._candles:
            self._render()

    def on_candle_closed(self, data: dict) -> None:
        """프로젝트에서 DataBus 구독 후 호출"""
        if data.get("symbol", "").upper() != self._symbol:
            return
        import time
        from .data_source import Candle
        try:
            ET = timezone(timedelta(hours=-4))
            minute = data.get("minute", "")
            if minute:
                today = datetime.now(tz=ET).strftime("%Y-%m-%d")
                dt    = datetime.strptime(
                    f"{today} {minute}", "%Y-%m-%d %H:%M").replace(tzinfo=ET)
                t_sec = int(dt.timestamp())
            else:
                t_sec = int(time.time())
            c = Candle(t_sec,
                       data.get("open",   0),
                       data.get("high",   0),
                       data.get("low",    0),
                       data.get("close",  0),
                       data.get("volume", 0))
            self._candles.append(c)
            self._live_bar = None
            self._render()
        except Exception as e:
            self._set_status(f"candle_closed 오류: {e}")

    # ── 테마 적용 ─────────────────────────────────────────────
    # 키움 라이트 테마 기본값 (#FFF5F7 연분홍, 텍스트 진회색, 격자 핑크빛)
    def apply_theme(self, bg: str = "#FFF5F7", fg: str = "#1E293B",
                    border: str = "#E8C8D0") -> None:
        try:
            if hasattr(self, "_gfx"):
                self._gfx.setBackground(bg)
            for pl in (getattr(self, "_p1", None),
                       getattr(self, "_p2", None)):
                if pl:
                    pl.getViewBox().setBackgroundColor(bg)
                    for ax in ("bottom", "left"):
                        pl.getAxis(ax).setTextPen(fg)
                        pl.getAxis(ax).setPen(border)
        except Exception:
            pass

    # ── 내부 유틸 ─────────────────────────────────────────────
    def _set_status(self, msg: str) -> None:
        if hasattr(self, "_status_lbl"):
            self._status_lbl.setText(msg)

    def _clear_chart(self) -> None:
        for pl in (getattr(self, "_p1", None),
                   getattr(self, "_p2", None)):
            if pl:
                try:
                    pl.clear()
                except Exception:
                    pass

    @pyqtSlot(object)
    def _on_status_msg(self, data) -> None:
        pass  # 필요 시 서브클래스에서 오버라이드

    # ── 종료 ─────────────────────────────────────────────────
    def closeEvent(self, e) -> None:
        if self._loader and self._loader.isRunning():
            self._loader.terminate()
            self._loader.wait(500)
        self._clear_chart()
        super().closeEvent(e)
