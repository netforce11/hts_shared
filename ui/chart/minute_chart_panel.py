# ui/chart/minute_chart_panel.py
# 분봉/일봉 차트 패널 — PyQt6, hts_shared BasePanel 상속
# Tradier_Working2/ui/minute_chart/minute_chart_panel.py 기반 재작성
#
# 각 프로젝트에서 사용법:
#   class MyChartPanel(MinuteChartPanel):
#       def _make_minute_loader(self, symbol, date):
#           return MyMinuteLoader(symbol, date)
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
    공통 분봉/일봉 차트 패널.
    데이터 로딩은 _make_minute_loader / _make_daily_loader 오버라이드로 주입.
    """
    PANEL_ID = "minute_chart"

    # 캔들 색상 (서브클래스에서 오버라이드 가능)
    UP_COLOR = "#26A69A"
    DN_COLOR = "#EF5350"

    def __init__(self, bus: DataBus, parent=None) -> None:
        super().__init__(bus, parent)
        self._symbol      = "AAPL"
        self._candles     = []
        self._loader      = None
        self._live_bar    = None          # 진행 중인 틱 데이터
        self._chart_mode  = "minute"      # "minute" | "daily"
        self._candle_item = None          # 닫힌 봉 아이템 (정적)
        self._live_item   = None          # 진행 중인 봉 아이템 (틱마다 교체)
        self._build_body()

        # DataBus 구독
        bus.subscribe(Topics.SYSTEM_STATUS, self,
                      lambda d: self._invoke_main("_on_status_msg", d))

    # ── 레이아웃 ─────────────────────────────────────────────
    def _build_body(self) -> None:
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

        # 캘린더 (분봉 모드에서만 의미 있음)
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

        # ── 상단 헤더 바 (Daily 토글 버튼) ───────────────────
        header = QHBoxLayout()
        header.setContentsMargins(8, 4, 8, 4)
        header.addStretch()

        self._btn_minute = QPushButton("1분봉")
        self._btn_daily  = QPushButton("Daily")
        for btn in (self._btn_minute, self._btn_daily):
            btn.setCheckable(True)
            btn.setFixedWidth(64)
            btn.setStyleSheet(
                "QPushButton { background:#334155; color:#94A3B8; border:1px solid #475569;"
                " border-radius:3px; padding:2px 6px; font-size:11px; }"
                "QPushButton:checked { background:#0EA5E9; color:#fff; border-color:#0EA5E9; }"
                "QPushButton:hover { background:#475569; }"
            )
        self._btn_minute.setChecked(True)
        self._btn_minute.clicked.connect(lambda: self._set_chart_mode("minute"))
        self._btn_daily.clicked.connect(lambda: self._set_chart_mode("daily"))

        header.addWidget(self._btn_minute)
        header.addWidget(self._btn_daily)

        header_w = QWidget()
        header_w.setLayout(header)
        header_w.setFixedHeight(32)        # Max 아닌 Fixed — Qt가 0으로 축소하는 것 방지
        lay.addWidget(header_w)

        # ── 차트 그래픽 영역 ─────────────────────────────────
        try:
            import pyqtgraph as pg
            pg.setConfigOptions(antialias=False, useOpenGL=False)

            self._gfx = pg.GraphicsLayoutWidget()
            self._gfx.setBackground("#FFF5F7")

            # p1 — 캔들
            self._p1 = self._gfx.addPlot(row=0, col=0)
            self._p1.showGrid(x=True, y=True, alpha=0.15)
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

            self._gfx.ci.layout.setRowStretchFactor(0, 4)
            self._gfx.ci.layout.setRowMinimumHeight(0, 150)
            self._gfx.ci.layout.setRowMaximumHeight(1, 80)
            self._gfx.ci.layout.setRowStretchFactor(1, 1)

            lay.addWidget(self._gfx, 1)
            self.apply_theme()
        except Exception as e:
            lay.addWidget(QLabel(f"pyqtgraph 오류: {e}"))
        return w

    # ── 단축키 선언 ───────────────────────────────────────────
    def register_shortcuts(self) -> list:
        return super().register_shortcuts() + [
            ("Left",  self._go_prev_day),
            ("Right", self._go_next_day),
            ("F5",    self._refresh),
            ("D",     lambda: self._set_chart_mode("daily")),
            ("M",     lambda: self._set_chart_mode("minute")),
        ]

    # ── 데이터 로더 주입 (서브클래스에서 오버라이드) ──────────
    def _make_minute_loader(self, symbol: str, target_date: date):
        """각 프로젝트에서 반드시 오버라이드"""
        raise NotImplementedError("_make_minute_loader를 오버라이드하세요")

    def _make_daily_loader(self, symbol: str, days: int = 60):
        """각 프로젝트에서 반드시 오버라이드"""
        raise NotImplementedError("_make_daily_loader를 오버라이드하세요")

    # ── 모드 토글 ─────────────────────────────────────────────
    def _set_chart_mode(self, mode: str) -> None:
        """'minute' 또는 'daily' 모드 전환"""
        if mode == self._chart_mode:
            return
        self._chart_mode = mode
        self._btn_minute.setChecked(mode == "minute")
        self._btn_daily.setChecked(mode == "daily")

        # 캘린더 비활성화 (일봉 모드에서는 날짜 선택 의미 없음)
        if hasattr(self, "_calendar"):
            self._calendar.setEnabled(mode == "minute")

        self._candles  = []
        self._live_bar = None
        self._clear_chart()

        if mode == "daily":
            self._load_daily()
        else:
            d = self._calendar.selectedDate().toPyDate()
            self._load_minute(d)

    # ── 사이드바 이벤트 ───────────────────────────────────────
    def _on_symbol_enter(self) -> None:
        sym = self._sym_input.currentText().strip().upper()
        if sym:
            self._set_symbol(sym)

    def _on_date_changed(self) -> None:
        if self._chart_mode == "minute":
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
        if self._chart_mode == "daily":
            self._load_daily()
        else:
            d = self._calendar.selectedDate().toPyDate()
            self._load_minute(d)

    def _set_symbol(self, symbol: str) -> None:
        self._symbol = symbol.upper()
        self._sym_input.setCurrentText(self._symbol)
        self._candles  = []
        self._live_bar = None
        self._clear_chart()
        if self._chart_mode == "daily":
            self._load_daily()
        else:
            d = self._calendar.selectedDate().toPyDate()
            self._load_minute(d)

    # ── 데이터 로드 ───────────────────────────────────────────
    def _load_minute(self, d: date) -> None:
        self._stop_loader()
        self._set_status(f"⏳ {d} 분봉 로딩 중...")
        self._candles  = []
        self._live_bar = None
        try:
            self._loader = self._make_minute_loader(self._symbol, d)
            self._loader.loaded.connect(self._on_minute_loaded)
            self._loader.error.connect(self._on_load_error)
            self._loader.start()
        except NotImplementedError:
            self._set_status("❌ _make_minute_loader 미구현")

    def _load_daily(self, days: int = 60) -> None:
        self._stop_loader()
        self._set_status(f"⏳ {self._symbol} 일봉 로딩 중 ({days}일)...")
        self._candles  = []
        self._live_bar = None
        try:
            self._loader = self._make_daily_loader(self._symbol, days)
            self._loader.loaded.connect(self._on_daily_loaded)
            self._loader.error.connect(self._on_load_error)
            self._loader.start()
        except NotImplementedError:
            self._set_status("❌ _make_daily_loader 미구현")

    def _stop_loader(self) -> None:
        if self._loader and self._loader.isRunning():
            self._loader.terminate()
            self._loader.wait(500)
        self._loader = None

    def _on_minute_loaded(self, candles: list) -> None:
        self._candles  = candles
        self._live_bar = None
        is_today = (self._calendar.selectedDate().toPyDate() == date.today())
        suffix = " | 📡 실시간" if is_today else ""
        self._set_status(f"✅ {len(candles)}봉 로드{suffix}")
        self._render_full()

    def _on_daily_loaded(self, candles: list) -> None:
        self._candles  = candles
        self._live_bar = None
        self._set_status(f"✅ 일봉 {len(candles)}일 로드")
        self._render_full()

    def _on_load_error(self, msg: str) -> None:
        self._set_status(f"❌ {msg}")

    # ── 렌더링 ────────────────────────────────────────────────
    def _render_full(self) -> None:
        """닫힌 봉 전체 재렌더. 새 데이터 수신·봉 확정 시 호출.
        live bar는 포함하지 않음 — 별도 _render_live_tick()이 담당."""
        if not hasattr(self, "_p1") or not self._candles:
            return
        try:
            import pyqtgraph as pg
            from .candle import CandlestickItem

            self._p1.clear()
            self._p2.clear()
            self._candle_item = None
            self._live_item   = None   # clear() 후이므로 plot에서 이미 제거됨

            valid = [c for c in self._candles
                     if c.h > 0 and c.l > 0 and c.o > 0 and c.c > 0
                     and c.h >= c.l and c.h >= c.o and c.h >= c.c]

            # ── live bar 는 여기서 포함하지 않음 ──
            # _render_full 후 live bar가 있으면 _render_live_tick이 이어서 추가
            display = list(valid)

            if not display:
                self._set_status("표시할 유효 캔들 없음")
                return

            # 캔들스틱
            self._candle_item = CandlestickItem(display, self.UP_COLOR, self.DN_COLOR)
            self._p1.addItem(self._candle_item)

            # 거래량 바
            xs     = list(range(len(display)))
            vs     = [max(c.v, 0) for c in display]
            colors = [self.UP_COLOR if c.c >= c.o else self.DN_COLOR
                      for c in display]
            bars = pg.BarGraphItem(x=xs, height=vs, width=0.6,
                                   brushes=colors, pens=colors)
            self._p2.addItem(bars)
            self._vol_bars = bars

            # Y/X 범위
            lows  = [c.l for c in display]
            highs = [c.h for c in display]
            y_min, y_max = min(lows), max(highs)
            span  = max(y_max - y_min, y_max * 0.001)
            pad   = span * 0.05
            self._p1.setYRange(y_min - pad, y_max + pad, padding=0)
            self._p1.setXRange(-1, len(display) + 1, padding=0)
            if vs:
                self._p2.setYRange(0, max(vs) * 1.1, padding=0)
                self._p2.setXRange(-1, len(display) + 1, padding=0)

            # x축 레이블
            self._set_x_ticks(display)

            # 닫힌 봉 렌더 후 live bar가 있으면 즉시 오버레이
            if self._live_bar:
                self._render_live_tick()

        except Exception as e:
            self._set_status(f"렌더 오류: {e}")

    def _render_live_tick(self) -> None:
        """
        틱 수신 시 live bar 아이템만 교체 (닫힌 봉 전체 재렌더 없음).
        깜빡임·덧칠 방지.
        """
        if not hasattr(self, "_p1") or not self._candle_item:
            # 아직 초기 full render 전 → full render로 처리
            self._render_full()
            return
        try:
            from .candle import CandlestickItem

            # 기존 live item 제거
            if self._live_item is not None:
                self._p1.removeItem(self._live_item)
                self._live_item = None

            lc = self._live_bar_as_candle()
            if not lc:
                return

            # live bar만 별도 아이템으로 오버레이
            self._live_item = CandlestickItem([lc], self.UP_COLOR, self.DN_COLOR,
                                              x_offset=len(self._candles))
            self._p1.addItem(self._live_item)

            # Y 범위: 기존 범위에 live bar 포함
            valid = [c for c in self._candles if c.h > 0 and c.l > 0]
            if valid:
                all_l = [c.l for c in valid] + [lc.l]
                all_h = [c.h for c in valid] + [lc.h]
                y_min, y_max = min(all_l), max(all_h)
                span = max(y_max - y_min, y_max * 0.001)
                pad  = span * 0.05
                self._p1.setYRange(y_min - pad, y_max + pad, padding=0)

        except Exception as e:
            self._set_status(f"live tick 렌더 오류: {e}")

    def _live_bar_as_candle(self):
        """self._live_bar dict → Candle (유효하지 않으면 None)"""
        if not self._live_bar:
            return None
        from .data_source import Candle
        import time
        try:
            o = float(self._live_bar.get("open",  0))
            h = float(self._live_bar.get("high",  0))
            l = float(self._live_bar.get("low",   0))
            c = float(self._live_bar.get("close", 0))
            v = int(self._live_bar.get("volume", 0))
            if o <= 0 or h <= 0 or l <= 0 or c <= 0:
                return None
            if h < l or h < o or h < c:
                return None
            t = int(self._live_bar.get("t", time.time()))
            return Candle(t, o, h, l, c, v)
        except Exception:
            return None

    def _set_x_ticks(self, candles: list) -> None:
        """모드에 따라 x축 레이블 설정"""
        ticks = {}
        step  = max(1, len(candles) // 10)
        if self._chart_mode == "daily":
            for i in range(0, len(candles), step):
                ticks[i] = datetime.fromtimestamp(candles[i].t).strftime("%m/%d")
        else:
            for i in range(0, len(candles), step):
                ticks[i] = datetime.fromtimestamp(candles[i].t).strftime("%H:%M")
        self._p1.getAxis("bottom").setTicks([list(ticks.items())])

    # ── 실시간 DataBus 토픽 ───────────────────────────────────
    def on_candle_tick(self, data: dict) -> None:
        """프로젝트에서 DataBus 구독 후 호출 (분봉 모드에서만 동작)"""
        if self._chart_mode != "minute":
            return
        if data.get("symbol", "").upper() != self._symbol:
            return
        self._live_bar = data
        # 전체 재렌더 대신 live item만 교체 → 깜빡임 없음
        self._render_live_tick()

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
            self._live_bar = None   # 봉 확정 → live bar 초기화

            # 봉이 닫혔을 때만 전체 재렌더
            self._render_full()
        except Exception as e:
            self._set_status(f"candle_closed 오류: {e}")

    # ── 테마 적용 ─────────────────────────────────────────────
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
        # live_item은 p1.clear()에 포함되지 않을 수 있으므로 명시적 제거
        if self._live_item is not None and hasattr(self, "_p1"):
            try:
                self._p1.removeItem(self._live_item)
            except Exception:
                pass
        self._candle_item = None
        self._live_item   = None
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
        self._stop_loader()
        self._clear_chart()
        super().closeEvent(e)
