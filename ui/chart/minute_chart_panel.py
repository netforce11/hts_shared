# ui/chart/minute_chart_panel.py
# 분봉/일봉 차트 패널 — PyQt6, hts_shared BasePanel 상속
#
# 각 프로젝트에서 사용법:
#   class MyChartPanel(MinuteChartPanel):
#       def _make_minute_loader(self, symbol, date):
#           return MyMinuteLoader(symbol, date)
#       def _make_daily_loader(self, symbol, days):
#           return MyDailyLoader(symbol, days)
#
# 신규 기능 (v2):
#   - p1:p2 배율 선택 드롭다운 (4:1 / 7:3 / 9:1 / 거래량 숨기기)
#   - 드로잉 툴바: 수평선·추세선·사각형·원·텍스트 + 수직 시간선 입력
#   - 2~5일 연속보기 (분봉 다일 이어붙이기, 날짜 경계선 표시)
#   - DataBus CHART_DATE_SELECT 구독 → 외부 캘린더 연동

from __future__ import annotations
from datetime  import date, datetime, timezone, timedelta

from PyQt6.QtWidgets import (
    QHBoxLayout, QVBoxLayout, QSplitter,
    QWidget, QLabel, QPushButton, QComboBox,
    QButtonGroup, QRadioButton, QCheckBox, QLineEdit,
)
from PyQt6.QtCore import Qt, QDate, pyqtSlot
from PyQt6.QtGui  import QFont

from ..panels.base_panel import BasePanel
from ...core.bus import DataBus
from ...core.topics import Topics


# ── 공통 스타일 상수 ──────────────────────────────────────────────
_BTN = (
    "QPushButton { background:#334155; color:#94A3B8; border:1px solid #475569;"
    " border-radius:3px; padding:2px 6px; font-size:11px; }"
    "QPushButton:checked { background:#0EA5E9; color:#fff; border-color:#0EA5E9; }"
    "QPushButton:hover { background:#475569; }"
)
_DRAW_BTN = (
    "QPushButton { background:#1E293B; color:#94A3B8; border:1px solid #334155;"
    " border-radius:3px; font-size:13px; }"
    "QPushButton:checked { background:#0EA5E9; color:#fff; border-color:#0EA5E9; }"
    "QPushButton:hover { background:#334155; }"
)
_COMBO = (
    "QComboBox { background:#1E293B; color:#E2E8F0; border:1px solid #334155;"
    " border-radius:3px; padding:2px 6px; font-size:11px; }"
    "QComboBox::drop-down { border:none; }"
    "QComboBox QAbstractItemView { background:#1E293B; color:#E2E8F0;"
    " border:1px solid #334155; selection-background-color:#0EA5E9; }"
)
_LINEEDIT = (
    "QLineEdit { background:#1E293B; color:#E2E8F0; border:1px solid #334155;"
    " border-radius:3px; padding:2px 4px; font-size:11px; }"
)
_LABEL = "QLabel { color:#94A3B8; font-size:11px; }"
_CHKBOX = "QCheckBox { color:#94A3B8; font-size:11px; }"
_RADIO  = "QRadioButton { color:#94A3B8; font-size:11px; }"


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
        self._live_bar    = None
        self._chart_mode  = "minute"
        self._candle_item = None
        self._live_item   = None
        self._x_time_map  = {}        # {x_idx: "HH:MM"} — 드로잉 시간선 등에 사용

        # 연속보기 상태
        self._multiday_dates:   list = []
        self._multiday_candles: list = []
        self._multiday_offsets: list = []   # 각 날의 시작 x 인덱스
        self._multiday_idx:     int  = 0

        self._build_body()

        # DataBus 구독
        bus.subscribe(Topics.SYSTEM_STATUS, self,
                      lambda d: self._invoke_main("_on_status_msg", d))
        # 외부 캘린더 연동 (관심종목 패널 하단 캘린더 등)
        bus.subscribe(Topics.CHART_DATE_SELECT, self,
                      lambda d: self._invoke_main("_on_ext_date_select", d))

    # ── 레이아웃 ─────────────────────────────────────────────────
    def _build_body(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_sidebar())
        splitter.addWidget(self._build_chart_area())
        splitter.setSizes([220, 900])
        splitter.setHandleWidth(4)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self._layout.addWidget(splitter, 1)   # stretch=1 → 남은 공간 모두 차지

        self._status_lbl = QLabel("대기 중...")
        self._status_lbl.setStyleSheet(_LABEL)
        self._layout.addWidget(self._status_lbl)

    # ── 사이드바 ──────────────────────────────────────────────────
    def _build_sidebar(self) -> QWidget:
        from PyQt6.QtWidgets import QCalendarWidget
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)

        # 심볼 입력
        sym_hdr = QHBoxLayout()
        sym_hdr.addWidget(QLabel("심볼"))
        sym_hdr.addStretch()
        # 캘린더 토글 버튼 (숨기면 차트 공간 확보)
        self._btn_cal_toggle = QPushButton("📅 날짜")
        self._btn_cal_toggle.setCheckable(True)
        self._btn_cal_toggle.setChecked(True)
        self._btn_cal_toggle.setFixedHeight(22)
        self._btn_cal_toggle.setStyleSheet(
            "QPushButton { background:#1E293B; color:#94A3B8; border:1px solid #334155;"
            " border-radius:3px; font-size:10px; padding:1px 6px; }"
            "QPushButton:checked { background:#1E4D2B; color:#86EFAC; border-color:#166534; }"
        )
        self._btn_cal_toggle.toggled.connect(self._on_cal_toggle)
        sym_hdr.addWidget(self._btn_cal_toggle)
        lay.addLayout(sym_hdr)

        self._sym_input = QComboBox()
        self._sym_input.setEditable(True)
        self._sym_input.addItems(["AAPL", "SPY", "QQQ", "TSLA", "NVDA"])
        self._sym_input.setCurrentText(self._symbol)
        self._sym_input.lineEdit().returnPressed.connect(self._on_symbol_enter)
        self._sym_input.setStyleSheet(_COMBO)
        lay.addWidget(self._sym_input)

        # 캘린더 컨테이너 (토글 가능)
        self._cal_w = QWidget()
        cal_lay = QVBoxLayout(self._cal_w)
        cal_lay.setContentsMargins(0, 4, 0, 0)
        cal_lay.setSpacing(2)
        cal_lay.addWidget(QLabel("날짜"))
        self._calendar = QCalendarWidget()
        self._calendar.setMaximumDate(QDate.currentDate())
        self._calendar.setSelectedDate(QDate.currentDate())
        self._calendar.selectionChanged.connect(self._on_date_changed)
        self._calendar.setFixedHeight(180)
        cal_lay.addWidget(self._calendar)

        # 이전/다음 버튼
        nav = QHBoxLayout()
        btn_prev = QPushButton("◀ 전날")
        btn_next = QPushButton("다음 ▶")
        btn_prev.clicked.connect(self._go_prev_day)
        btn_next.clicked.connect(self._go_next_day)
        btn_prev.setStyleSheet(_BTN)
        btn_next.setStyleSheet(_BTN)
        nav.addWidget(btn_prev)
        nav.addWidget(btn_next)
        cal_lay.addLayout(nav)
        lay.addWidget(self._cal_w)

        # ── 일봉 기간 선택 (Daily 모드 전용) ─────────────────
        self._daily_period_w = QWidget()
        dp_lay = QVBoxLayout(self._daily_period_w)
        dp_lay.setContentsMargins(0, 4, 0, 0)
        dp_lay.setSpacing(2)
        dp_lay.addWidget(QLabel("일봉 기간"))

        self._daily_period_grp = QButtonGroup(self)
        for days in [60, 90, 120, 150]:
            rb = QRadioButton(f"{days}일")
            rb.setProperty("days", days)
            rb.setStyleSheet(_RADIO)
            if days == 150:
                rb.setChecked(True)
            self._daily_period_grp.addButton(rb)
            dp_lay.addWidget(rb)

        self._daily_period_grp.buttonClicked.connect(
            self._on_daily_period_changed)
        self._daily_period_w.setVisible(False)
        lay.addWidget(self._daily_period_w)

        lay.addStretch()
        return w

    # ── 차트 영역 ─────────────────────────────────────────────────
    def _build_chart_area(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        lay.addWidget(self._build_ctrl_bar())   # 40px: 봉종류·배율·연속보기
        lay.addWidget(self._build_draw_bar())   # 36px: 드로잉 툴바

        # ── pyqtgraph 차트 ───────────────────────────────────
        try:
            import pyqtgraph as pg
            pg.setConfigOptions(antialias=False, useOpenGL=False)

            self._gfx = pg.GraphicsLayoutWidget()
            self._gfx.setBackground("#FFF5F7")

            self._p1 = self._gfx.addPlot(row=0, col=0)
            self._p1.showGrid(x=True, y=True, alpha=0.15)
            self._p1.setLabel("left", "가격")
            self._p1.setMenuEnabled(False)

            self._gfx.nextRow()
            self._p2 = self._gfx.addPlot(row=1, col=0)
            self._p2.setXLink(self._p1)
            self._p2.setLabel("left", "거래량")
            self._p2.setMenuEnabled(False)
            self._p2.hideAxis("bottom")

            # 기본 배율 4:1 (p1 : p2)
            ci = self._gfx.ci.layout
            ci.setRowStretchFactor(0, 4)
            ci.setRowStretchFactor(1, 1)
            ci.setRowMinimumHeight(0, 150)
            ci.setRowMinimumHeight(1, 30)

            lay.addWidget(self._gfx, 1)
            self.apply_theme()

            # 드로잉 매니저 — p1이 준비된 후 초기화
            from .drawing_manager import DrawingManager
            self._draw_mgr = DrawingManager(
                self._p1,
                x_time_map_provider=lambda: self._x_time_map
            )

        except Exception as e:
            lay.addWidget(QLabel(f"pyqtgraph 오류: {e}"))
        return w

    def _build_ctrl_bar(self) -> QWidget:
        """상단 제어 바: 봉 종류 | 배율 | 연속보기"""
        w   = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(6)
        w.setFixedHeight(40)
        w.setStyleSheet(
            "QWidget { background-color: #1E2A3A; border-bottom: 1px solid #334155; }"
        )

        # 봉 종류 버튼
        self._btn_minute = QPushButton("1분봉")
        self._btn_daily  = QPushButton("Daily")
        for btn in (self._btn_minute, self._btn_daily):
            btn.setCheckable(True)
            btn.setFixedWidth(64)
            btn.setStyleSheet(_BTN)
        self._btn_minute.setChecked(True)
        self._btn_minute.clicked.connect(lambda: self._set_chart_mode("minute"))
        self._btn_daily.clicked.connect(lambda: self._set_chart_mode("daily"))
        lay.addWidget(self._btn_minute)
        lay.addWidget(self._btn_daily)

        sep = QLabel("|")
        sep.setStyleSheet("color:#475569; font-size:14px;")
        lay.addWidget(sep)

        # p1:p2 배율 선택
        lbl_r = QLabel("배율:")
        lbl_r.setStyleSheet(_LABEL)
        lay.addWidget(lbl_r)
        self._ratio_combo = QComboBox()
        self._ratio_combo.addItems(["4:1", "7:3", "9:1", "거래량 숨기기"])
        self._ratio_combo.setCurrentText("4:1")
        self._ratio_combo.setFixedWidth(110)
        self._ratio_combo.setStyleSheet(_COMBO)
        self._ratio_combo.currentTextChanged.connect(self._on_ratio_changed)
        lay.addWidget(self._ratio_combo)

        lay.addStretch()

        # 연속보기 체크박스
        self._chk_multiday = QCheckBox("연속보기")
        self._chk_multiday.setStyleSheet(_CHKBOX)
        self._chk_multiday.stateChanged.connect(self._on_multiday_toggled)
        lay.addWidget(self._chk_multiday)

        # 연속 일 수 선택 (2~5일) — 연속보기 체크 시만 보임
        self._multiday_day_w = QWidget()
        md_lay = QHBoxLayout(self._multiday_day_w)
        md_lay.setContentsMargins(4, 0, 0, 0)
        md_lay.setSpacing(2)
        self._multiday_grp = QButtonGroup(self)
        for n in [2, 3, 4, 5]:
            rb = QRadioButton(f"{n}일")
            rb.setProperty("ndays", n)
            rb.setStyleSheet(_RADIO)
            if n == 2:
                rb.setChecked(True)
            self._multiday_grp.addButton(rb)
            md_lay.addWidget(rb)
        self._multiday_grp.buttonClicked.connect(
            lambda _: self._on_multiday_count_changed())
        self._multiday_day_w.setVisible(False)
        lay.addWidget(self._multiday_day_w)

        return w

    def _build_draw_bar(self) -> QWidget:
        """드로잉 툴바: 드로잉 모드 버튼 + 수직 시간선 입력 + 지우기"""
        w   = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(8, 2, 8, 2)
        lay.setSpacing(4)
        w.setFixedHeight(36)
        w.setStyleSheet(
            "QWidget { background-color: #141E2E; border-bottom: 1px solid #263040; }"
        )

        # 드로잉 모드 버튼 (상호 배타적)
        self._draw_mode_grp = QButtonGroup(self)
        self._draw_mode_grp.setExclusive(True)

        MODES = [
            ("▷", "select",  "선택 모드 (드로잉 없음)"),
            ("─", "h_line",  "수평선: 클릭"),
            ("╱", "trend",   "추세선: 클릭 2회"),
            ("□", "rect",    "사각형: 클릭 2회 (좌상-우하)"),
            ("○", "ellipse", "원/타원: 클릭 2회"),
            ("T", "text",    "텍스트: 클릭 후 입력"),
        ]
        for lbl, mode, tip in MODES:
            btn = QPushButton(lbl)
            btn.setCheckable(True)
            btn.setFixedSize(28, 26)
            btn.setToolTip(tip)
            btn.setProperty("draw_mode", mode)
            btn.setStyleSheet(_DRAW_BTN)
            if mode == "select":
                btn.setChecked(True)
            self._draw_mode_grp.addButton(btn)
            lay.addWidget(btn)
        self._draw_mode_grp.buttonClicked.connect(self._on_draw_mode_changed)

        # 구분선
        s1 = QLabel("│")
        s1.setStyleSheet("color:#334155; font-size:16px;")
        lay.addWidget(s1)

        # 수직 시간선 입력
        lbl_t = QLabel("시간선:")
        lbl_t.setStyleSheet(_LABEL)
        lay.addWidget(lbl_t)
        self._vline_input = QLineEdit()
        self._vline_input.setPlaceholderText("09:30")
        self._vline_input.setFixedWidth(56)
        self._vline_input.setStyleSheet(_LINEEDIT)
        self._vline_input.returnPressed.connect(self._on_add_vline)
        lay.addWidget(self._vline_input)

        btn_vline = QPushButton("추가")
        btn_vline.setFixedHeight(24)
        btn_vline.setStyleSheet(
            "QPushButton { background:#1E4D2B; color:#86EFAC; border:1px solid #166534;"
            " border-radius:3px; font-size:10px; padding:0 6px; }"
            "QPushButton:hover { background:#166534; }"
        )
        btn_vline.clicked.connect(self._on_add_vline)
        lay.addWidget(btn_vline)

        lay.addStretch()

        # 지우기 버튼
        btn_clear = QPushButton("🗑 지우기")
        btn_clear.setFixedHeight(26)
        btn_clear.setStyleSheet(
            "QPushButton { background:#3D1515; color:#FCA5A5; border:1px solid #7F1D1D;"
            " border-radius:3px; font-size:11px; padding:0 8px; }"
            "QPushButton:hover { background:#7F1D1D; }"
        )
        btn_clear.clicked.connect(self._on_draw_clear)
        lay.addWidget(btn_clear)

        return w

    # ── 단축키 ───────────────────────────────────────────────────
    def register_shortcuts(self) -> list:
        return super().register_shortcuts() + [
            ("Left",  self._go_prev_day),
            ("Right", self._go_next_day),
            ("F5",    self._refresh),
            ("D",     lambda: self._set_chart_mode("daily")),
            ("M",     lambda: self._set_chart_mode("minute")),
        ]

    # ── 데이터 로더 주입 (서브클래스 오버라이드) ──────────────────
    def _make_minute_loader(self, symbol: str, target_date: date):
        raise NotImplementedError("_make_minute_loader를 오버라이드하세요")

    def _make_daily_loader(self, symbol: str, days: int = 60):
        raise NotImplementedError("_make_daily_loader를 오버라이드하세요")

    # ── 모드 전환 ────────────────────────────────────────────────
    def _set_chart_mode(self, mode: str) -> None:
        if mode == self._chart_mode:
            return
        self._chart_mode = mode
        self._btn_minute.setChecked(mode == "minute")
        self._btn_daily.setChecked(mode == "daily")

        if hasattr(self, "_cal_w"):
            self._cal_w.setEnabled(mode == "minute")
        if hasattr(self, "_daily_period_w"):
            self._daily_period_w.setVisible(mode == "daily")

        # 연속보기는 분봉 전용 — Daily 모드로 전환 시 숨김
        if hasattr(self, "_chk_multiday"):
            self._chk_multiday.setVisible(mode == "minute")
        if hasattr(self, "_multiday_day_w"):
            visible = (mode == "minute"
                       and hasattr(self, "_chk_multiday")
                       and self._chk_multiday.isChecked())
            self._multiday_day_w.setVisible(visible)

        self._candles  = []
        self._live_bar = None
        self._clear_chart()

        if mode == "daily":
            self._load_daily()
        else:
            d = self._calendar.selectedDate().toPyDate()
            self._load_minute_or_multi(d)

    # ── 사이드바 이벤트 ──────────────────────────────────────────
    def _on_cal_toggle(self, checked: bool) -> None:
        if hasattr(self, "_cal_w"):
            self._cal_w.setVisible(checked)

    def _on_symbol_enter(self) -> None:
        sym = self._sym_input.currentText().strip().upper()
        if sym:
            self._set_symbol(sym)

    def _on_date_changed(self) -> None:
        if self._chart_mode == "minute":
            d = self._calendar.selectedDate().toPyDate()
            self._load_minute_or_multi(d)

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
            self._load_minute_or_multi(d)

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
            self._load_minute_or_multi(d)

    def _load_minute_or_multi(self, d: date) -> None:
        """연속보기 활성화 여부에 따라 적절한 로더 선택"""
        if (hasattr(self, "_chk_multiday")
                and self._chk_multiday.isChecked()):
            self._load_multiday()
        else:
            self._load_minute(d)

    # ── 배율 변경 ────────────────────────────────────────────────
    def _on_ratio_changed(self, text: str) -> None:
        if not hasattr(self, "_gfx"):
            return
        ci = self._gfx.ci.layout
        if text == "거래량 숨기기":
            ci.setRowMaximumHeight(1, 0)
            ci.setRowStretchFactor(1, 0)
        else:
            # 최대 높이 제한 해제 후 stretch 비율 적용
            ci.setRowMaximumHeight(1, 16777215)
            try:
                n, d = (int(v) for v in text.split(":"))
                ci.setRowStretchFactor(0, n)
                ci.setRowStretchFactor(1, d)
            except (ValueError, AttributeError):
                ci.setRowStretchFactor(0, 4)
                ci.setRowStretchFactor(1, 1)

    # ── 연속보기 ─────────────────────────────────────────────────
    def _on_multiday_toggled(self, state: int) -> None:
        checked = bool(state)
        if hasattr(self, "_multiday_day_w"):
            self._multiday_day_w.setVisible(checked)
        if self._chart_mode != "minute":
            return
        if checked:
            self._load_multiday()
        else:
            # 단일 날 로드로 복귀
            d = self._calendar.selectedDate().toPyDate()
            self._load_minute(d)

    def _on_multiday_count_changed(self) -> None:
        """일 수 라디오버튼 변경 시 재로드"""
        if (self._chart_mode == "minute"
                and hasattr(self, "_chk_multiday")
                and self._chk_multiday.isChecked()):
            self._load_multiday()

    def _get_multiday_count(self) -> int:
        if hasattr(self, "_multiday_grp"):
            btn = self._multiday_grp.checkedButton()
            if btn:
                return btn.property("ndays")
        return 2

    def _load_multiday(self) -> None:
        """연속보기: 선택된 날 포함 n 거래일 분봉 순차 로드"""
        n        = self._get_multiday_count()
        end_date = self._calendar.selectedDate().toPyDate()

        # n 거래일 수집 (오래된 날 → 최신 날 순)
        dates: list[date] = []
        d = end_date
        while len(dates) < n:
            if d.weekday() < 5:
                dates.append(d)
            d -= timedelta(days=1)
        dates.reverse()

        self._multiday_dates   = dates
        self._multiday_candles = []
        self._multiday_offsets = []
        self._multiday_idx     = 0
        self._candles          = []
        self._live_bar         = None
        self._clear_chart()
        self._load_multiday_next()

    def _load_multiday_next(self) -> None:
        if self._multiday_idx >= len(self._multiday_dates):
            # 모든 날 로드 완료
            self._candles  = list(self._multiday_candles)
            self._live_bar = None
            n_days = len(self._multiday_dates)
            n_bars = len(self._candles)
            self._set_status(f"✅ 연속 {n_days}일 {n_bars}봉 로드")
            self._render_full()
            return

        d     = self._multiday_dates[self._multiday_idx]
        total = len(self._multiday_dates)
        self._set_status(
            f"⏳ {d} 분봉 로딩... ({self._multiday_idx + 1}/{total})")
        self._stop_loader()
        try:
            self._loader = self._make_minute_loader(self._symbol, d)
            self._loader.loaded.connect(self._on_multiday_partial_loaded)
            self._loader.error.connect(self._on_load_error)
            self._loader.start()
        except NotImplementedError:
            self._set_status("❌ _make_minute_loader 미구현")

    def _on_multiday_partial_loaded(self, candles: list) -> None:
        """한 날 분봉 로드 완료 → 다음 날 로드"""
        # guard: 상태가 이미 리셋된 경우 무시
        if self._multiday_idx >= len(self._multiday_dates):
            return
        self._multiday_offsets.append(len(self._multiday_candles))
        self._multiday_candles.extend(candles)
        self._multiday_idx += 1
        self._load_multiday_next()

    # ── 일봉 기간 ────────────────────────────────────────────────
    def _get_daily_days(self) -> int:
        if hasattr(self, "_daily_period_grp"):
            btn = self._daily_period_grp.checkedButton()
            if btn:
                return btn.property("days")
        return 150

    def _on_daily_period_changed(self) -> None:
        if self._chart_mode == "daily":
            self._load_daily()

    # ── 데이터 로드 ──────────────────────────────────────────────
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

    def _load_daily(self, days: int = 0) -> None:
        if days <= 0:
            days = self._get_daily_days()
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
        self._set_status(
            f"✅ {len(candles)}봉 로드{' | 📡 실시간' if is_today else ''}")
        self._render_full()

    def _on_daily_loaded(self, candles: list) -> None:
        self._candles  = candles
        self._live_bar = None
        self._set_status(f"✅ 일봉 {len(candles)}일 로드")
        self._render_full()

    def _on_load_error(self, msg: str) -> None:
        self._set_status(f"❌ {msg}")

    # ── 렌더링 ───────────────────────────────────────────────────
    def _render_full(self) -> None:
        """닫힌 봉 전체 재렌더. live bar 제외 — _render_live_tick 별도 처리."""
        if not hasattr(self, "_p1") or not self._candles:
            return
        try:
            import pyqtgraph as pg
            from .candle import CandlestickItem
            from PyQt6.QtCore import Qt

            self._p1.getViewBox().setAutoVisible(y=False)
            self._p1.clear()
            self._p2.clear()
            self._candle_item = None
            self._live_item   = None

            # 드로잉 아이템: clear 후 내부 목록 정리
            if hasattr(self, "_draw_mgr"):
                self._draw_mgr.remove_all_from_p1()

            valid = [c for c in self._candles
                     if c.h > 0 and c.l > 0 and c.o > 0 and c.c > 0
                     and c.h >= c.l and c.h >= c.o and c.h >= c.c]
            display = list(valid)
            if not display:
                self._set_status("표시할 유효 캔들 없음")
                return

            # 캔들스틱
            self._candle_item = CandlestickItem(
                display, self.UP_COLOR, self.DN_COLOR)
            self._p1.addItem(self._candle_item)

            # 거래량 바
            xs     = list(range(len(display)))
            vs     = [max(c.v, 0) for c in display]
            colors = [self.UP_COLOR if c.c >= c.o else self.DN_COLOR
                      for c in display]
            self._p2.addItem(pg.BarGraphItem(
                x=xs, height=vs, width=0.6, brushes=colors, pens=colors))

            # Y/X 범위
            lows  = [c.l for c in display]
            highs = [c.h for c in display]
            y_min, y_max = min(lows), max(highs)
            span = max(y_max - y_min, y_max * 0.005)
            pad  = span * 0.1
            self._p1.setYRange(y_min - pad, y_max + pad, padding=0)
            self._p1.setXRange(-0.5, len(display) + 2.5, padding=0)
            if vs:
                self._p2.setYRange(0, max(vs) * 1.1, padding=0)
                self._p2.setXRange(-0.5, len(display) + 2.5, padding=0)

            # x축 레이블 + _x_time_map 갱신
            self._set_x_ticks(display)

            # 연속보기 날짜 경계선
            self._draw_day_boundaries(display)

            # live bar 오버레이
            if self._live_bar:
                self._render_live_tick()

        except Exception as e:
            self._set_status(f"렌더 오류: {e}")

    def _draw_day_boundaries(self, display: list) -> None:
        """연속보기 모드: 날짜 경계에 수직 점선 표시"""
        if not (hasattr(self, "_chk_multiday")
                and self._chk_multiday.isChecked()):
            return
        if len(self._multiday_offsets) < 2:
            return
        try:
            import pyqtgraph as pg
            from PyQt6.QtCore import Qt
            for offset in self._multiday_offsets[1:]:   # 첫 번째(0) 제외
                if 0 < offset <= len(display):
                    line = pg.InfiniteLine(
                        pos=offset - 0.5, angle=90,
                        pen=pg.mkPen(
                            "#64748B", width=1,
                            style=Qt.PenStyle.DashLine)
                    )
                    self._p1.addItem(line)
        except Exception:
            pass

    def _render_live_tick(self) -> None:
        """틱 수신 시 live bar 아이템만 교체 (닫힌 봉 재렌더 없음)"""
        if not hasattr(self, "_p1") or not self._candle_item:
            self._render_full()
            return
        try:
            from .candle import CandlestickItem

            if self._live_item is not None:
                self._p1.removeItem(self._live_item)
                self._live_item = None

            lc = self._live_bar_as_candle()
            if not lc:
                return

            self._live_item = CandlestickItem(
                [lc], self.UP_COLOR, self.DN_COLOR,
                x_offset=len(self._candles))
            self._p1.addItem(self._live_item)

            valid = [c for c in self._candles if c.h > 0 and c.l > 0]
            if valid:
                all_l = [c.l for c in valid] + [lc.l]
                all_h = [c.h for c in valid] + [lc.h]
                y_min, y_max = min(all_l), max(all_h)
                span = max(y_max - y_min, y_max * 0.005)
                pad  = span * 0.1
                self._p1.setYRange(y_min - pad, y_max + pad, padding=0)
            x_end = len(self._candles) + 1
            self._p1.setXRange(-0.5, x_end + 1.5, padding=0)

        except Exception as e:
            self._set_status(f"live tick 오류: {e}")

    def _live_bar_as_candle(self):
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
        """x축 레이블 + _x_time_map 갱신
        _x_time_map은 수직 시간선 추가 시 HH:MM → x인덱스 변환에 사용"""
        ticks:       dict = {}
        self._x_time_map  = {}
        step = max(1, len(candles) // 10)

        if self._chart_mode == "daily":
            for i in range(0, len(candles), step):
                ticks[i] = datetime.fromtimestamp(
                    candles[i].t).strftime("%m/%d")
        else:
            for i, c in enumerate(candles):
                t_str = datetime.fromtimestamp(c.t).strftime("%H:%M")
                self._x_time_map[i] = t_str
                if i % step == 0:
                    ticks[i] = t_str

        self._p1.getAxis("bottom").setTicks([list(ticks.items())])

    # ── 드로잉 툴 이벤트 ────────────────────────────────────────
    def _on_draw_mode_changed(self, btn) -> None:
        mode = btn.property("draw_mode")
        if hasattr(self, "_draw_mgr"):
            self._draw_mgr.set_mode(mode)

    def _on_add_vline(self) -> None:
        """수직 시간선 추가 (시간 입력 필드 → 차트 x 위치 변환)"""
        if not hasattr(self, "_draw_mgr"):
            return
        text = self._vline_input.text().strip()
        if not text:
            return
        # "930" 또는 "0930" → "09:30" 변환
        if ":" not in text:
            if len(text) == 3:
                text = f"0{text[0]}:{text[1:]}"
            elif len(text) == 4:
                text = f"{text[:2]}:{text[2:]}"
        # _x_time_map에서 x 위치 탐색
        x_map = self._x_time_map
        x_pos = None
        for xi, t_str in x_map.items():
            if t_str == text:
                x_pos = xi
                break
        if x_pos is not None:
            self._draw_mgr.add_vline_at_x(float(x_pos), text)
            self._vline_input.clear()
        else:
            self._set_status(
                f"'{text}' 시간을 차트에서 찾을 수 없음 (분봉 차트에서만 사용)")

    def _on_draw_clear(self) -> None:
        if hasattr(self, "_draw_mgr"):
            self._draw_mgr.clear_all()

    # ── 실시간 DataBus ───────────────────────────────────────────
    def on_candle_tick(self, data: dict) -> None:
        if self._chart_mode != "minute":
            return
        if data.get("symbol", "").upper() != self._symbol:
            return
        self._live_bar = data
        self._render_live_tick()

    def on_candle_closed(self, data: dict) -> None:
        if data.get("symbol", "").upper() != self._symbol:
            return
        import time
        from .data_source import Candle
        try:
            ET     = timezone(timedelta(hours=-4))
            minute = data.get("minute", "")
            if minute:
                today = datetime.now(tz=ET).strftime("%Y-%m-%d")
                dt    = datetime.strptime(
                    f"{today} {minute}", "%Y-%m-%d %H:%M"
                ).replace(tzinfo=ET)
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
            self._render_full()
        except Exception as e:
            self._set_status(f"candle_closed 오류: {e}")

    # ── 외부 캘린더 연동 (DataBus) ──────────────────────────────
    @pyqtSlot(object)
    def _on_ext_date_select(self, data) -> None:
        """
        DataBus CHART_DATE_SELECT 수신 → 날짜 전환.
        관심종목 패널 하단에 캘린더를 놓고 이 토픽을 발행하면
        차트 패널이 자동으로 해당 날의 분봉을 로드한다.

        payload: {"date": "YYYY-MM-DD"} 또는 datetime.date 객체
        """
        try:
            d = data.get("date") if isinstance(data, dict) else data
            if isinstance(d, str):
                d = date.fromisoformat(d)
            if not isinstance(d, date):
                return
            qd = QDate(d.year, d.month, d.day)
            # setSelectedDate → selectionChanged → _on_date_changed → 로드
            self._calendar.setSelectedDate(qd)
        except Exception as e:
            self._set_status(f"외부 날짜 선택 오류: {e}")

    # ── 테마 ─────────────────────────────────────────────────────
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

    # ── 유틸 ─────────────────────────────────────────────────────
    def _set_status(self, msg: str) -> None:
        if hasattr(self, "_status_lbl"):
            self._status_lbl.setText(msg)

    def _clear_chart(self) -> None:
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
        # pl.clear() 후 드로잉 내부 참조 정리
        if hasattr(self, "_draw_mgr"):
            self._draw_mgr.remove_all_from_p1()

    @pyqtSlot(object)
    def _on_status_msg(self, data) -> None:
        pass  # 필요 시 서브클래스에서 오버라이드

    # ── 종료 ─────────────────────────────────────────────────────
    def closeEvent(self, e) -> None:
        self._stop_loader()
        self._clear_chart()
        super().closeEvent(e)
