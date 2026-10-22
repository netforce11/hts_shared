# ui/chart/drawing_manager.py
"""
pyqtgraph 캔들차트 드로잉 도구 매니저.

지원 모드
  select   : 기본 (뷰박스 기본 동작 유지)
  h_line   : 수평선 — 클릭 위치에 이동 가능한 가로선
  trend    : 추세선 — 클릭 2회로 선분 확정
  rect     : 사각형 — 클릭 2회 (좌상/우하)
  ellipse  : 원/타원 — 클릭 2회 (좌상/우하 bounding)
  text     : 텍스트 — 클릭 위치에 팝업 입력 후 레이블

수직 시간선 (v_line) 은 DrawingManager 클릭 모드가 아닌
별도 시간 입력 UI를 통해 추가한다 → add_vline_at_x() 직접 호출.
"""
from __future__ import annotations


class DrawingManager:
    SELECT  = "select"
    H_LINE  = "h_line"
    TREND   = "trend"
    RECT    = "rect"
    ELLIPSE = "ellipse"
    TEXT    = "text"

    # 색상
    COLOR_LINE  = "#F59E0B"   # 황금색 — 드로잉 기본
    COLOR_VLINE = "#60A5FA"   # 파란색 — 수직 시간선
    COLOR_TEXT  = "#E2E8F0"   # 밝은 회색 — 텍스트

    def __init__(self, p1, x_time_map_provider=None):
        """
        p1                 : pyqtgraph PlotItem (캔들 플롯)
        x_time_map_provider: callable → {x_idx: "HH:MM"}
                             수직 시간선 x 위치 계산에 사용
        """
        self._p1    = p1
        self._mode  = self.SELECT
        self._items: list = []       # 확정된 드로잉 아이템
        self._tmp   = None           # 마우스 이동 중 프리뷰 아이템
        self._pt1   = None           # 첫 번째 클릭 좌표 (x, y)
        self._xtm   = x_time_map_provider  # callable or None

        # scene 이벤트 연결
        scene = p1.getViewBox().scene()
        scene.sigMouseClicked.connect(self._on_click)
        scene.sigMouseMoved.connect(self._on_move)

    # ── 외부 API ──────────────────────────────────────────────────
    def set_mode(self, mode: str) -> None:
        """드로잉 모드 전환. 진행 중인 임시 아이템 취소."""
        self._mode = mode
        self._cancel_tmp()

    def clear_all(self) -> None:
        """모든 드로잉 아이템 제거 (p1에서 삭제 + 내부 목록 초기화)"""
        for item in list(self._items):
            try:
                self._p1.removeItem(item)
            except Exception:
                pass
        self._items.clear()
        self._cancel_tmp()

    def remove_all_from_p1(self) -> None:
        """p1.clear() 호출 후 내부 참조만 정리
        (아이템은 이미 plot에서 사라진 경우 사용)"""
        self._items.clear()
        self._tmp  = None
        self._pt1  = None

    def add_vline_at_x(self, x: float, label: str = "") -> None:
        """수직 시간선을 x 위치에 즉시 추가 (외부 UI 입력 → 호출)"""
        import pyqtgraph as pg
        from PyQt6.QtCore import Qt
        line = pg.InfiniteLine(
            pos=x, angle=90,
            pen=pg.mkPen(self.COLOR_VLINE, width=1,
                         style=Qt.PenStyle.DashLine),
            label=label,
            labelOpts={"color": self.COLOR_VLINE,
                       "fill": "#1E293B90", "movable": False}
        )
        self._p1.addItem(line)
        self._items.append(line)

    # ── 마우스 이벤트 ─────────────────────────────────────────────
    def _vb(self):
        return self._p1.getViewBox()

    def _map(self, scene_pos):
        """scene 좌표 → data 좌표"""
        return self._vb().mapSceneToView(scene_pos)

    def _cancel_tmp(self) -> None:
        if self._tmp is not None:
            try:
                self._p1.removeItem(self._tmp)
            except Exception:
                pass
            self._tmp = None
        self._pt1 = None

    def _pen(self, color: str, width: int = 1, dash: bool = False):
        import pyqtgraph as pg
        from PyQt6.QtCore import Qt
        style = Qt.PenStyle.DashLine if dash else Qt.PenStyle.SolidLine
        return pg.mkPen(color, width=width, style=style)

    def _on_click(self, event) -> None:
        if self._mode == self.SELECT:
            return
        from PyQt6.QtCore import Qt as _Qt
        if event.button() != _Qt.MouseButton.LeftButton:   # 좌클릭만 (PyQt6 enum)
            self._cancel_tmp()
            return

        pos  = self._map(event.scenePos())
        x, y = pos.x(), pos.y()

        if self._mode == self.H_LINE:
            self._finish_hline(y)

        elif self._mode == self.TEXT:
            self._finish_text(x, y)

        elif self._mode in (self.TREND, self.RECT, self.ELLIPSE):
            if self._pt1 is None:
                self._pt1 = (x, y)
            else:
                x1, y1 = self._pt1
                if self._mode == self.TREND:
                    self._finish_trend(x1, y1, x, y)
                elif self._mode == self.RECT:
                    self._finish_rect(x1, y1, x, y)
                elif self._mode == self.ELLIPSE:
                    self._finish_ellipse(x1, y1, x, y)
                # 임시 프리뷰 제거
                if self._tmp is not None:
                    try:
                        self._p1.removeItem(self._tmp)
                    except Exception:
                        pass
                    self._tmp = None
                self._pt1 = None

        event.accept()

    def _on_move(self, scene_pos) -> None:
        """마우스 이동 중 프리뷰 렌더링"""
        if self._pt1 is None or self._mode == self.SELECT:
            return
        import pyqtgraph as pg
        pos  = self._map(scene_pos)
        x2, y2 = pos.x(), pos.y()
        x1, y1 = self._pt1

        # 기존 임시 아이템 제거
        if self._tmp is not None:
            try:
                self._p1.removeItem(self._tmp)
            except Exception:
                pass
            self._tmp = None

        if self._mode == self.TREND:
            self._tmp = pg.PlotDataItem(
                x=[x1, x2], y=[y1, y2],
                pen=self._pen(self.COLOR_LINE, 1, dash=True)
            )
            self._p1.addItem(self._tmp)

        elif self._mode in (self.RECT, self.ELLIPSE):
            rw, rh = abs(x2 - x1), abs(y2 - y1)
            if rw < 0.001 or rh < 0.001:
                return
            pen = self._pen(self.COLOR_LINE, 1, dash=True)
            if self._mode == self.RECT:
                # PlotDataItem은 데이터 좌표계 사용 — QGraphicsRectItem(씬 좌표) 사용 금지
                tmp = pg.PlotDataItem(
                    x=[x1, x2, x2, x1, x1],
                    y=[y1, y1, y2, y2, y1],
                    pen=pen,
                )
            else:
                # 타원: 데이터 좌표 폴리곤 근사
                import math
                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                rx2, ry2 = rw / 2, rh / 2
                n = 64
                xs = [cx + rx2 * math.cos(2 * math.pi * i / n) for i in range(n + 1)]
                ys = [cy + ry2 * math.sin(2 * math.pi * i / n) for i in range(n + 1)]
                tmp = pg.PlotDataItem(x=xs, y=ys, pen=pen)
            self._p1.addItem(tmp)
            self._tmp = tmp

    # ── 확정 아이템 생성 ──────────────────────────────────────────
    def _finish_hline(self, y: float) -> None:
        import pyqtgraph as pg
        line = pg.InfiniteLine(
            pos=y, angle=0, movable=True,
            pen=self._pen(self.COLOR_LINE, 1),
            label=f"{y:.2f}",
            labelOpts={"color": self.COLOR_LINE,
                       "fill": "#1E293B90", "position": 0.9}
        )
        self._p1.addItem(line)
        self._items.append(line)

    def _finish_trend(self, x1, y1, x2, y2) -> None:
        import pyqtgraph as pg
        item = pg.PlotDataItem(
            x=[x1, x2], y=[y1, y2],
            pen=self._pen(self.COLOR_LINE, 1)
        )
        self._p1.addItem(item)
        self._items.append(item)

    def _finish_rect(self, x1, y1, x2, y2) -> None:
        import pyqtgraph as pg
        # QGraphicsRectItem은 씬(픽셀) 좌표계 → 데이터 좌표 폴리곤으로 대체
        item = pg.PlotDataItem(
            x=[x1, x2, x2, x1, x1],
            y=[y1, y1, y2, y2, y1],
            pen=self._pen(self.COLOR_LINE, 1),
        )
        self._p1.addItem(item)
        self._items.append(item)

    def _finish_ellipse(self, x1, y1, x2, y2) -> None:
        import pyqtgraph as pg
        import math
        # QGraphicsEllipseItem은 씬(픽셀) 좌표계 → 데이터 좌표 폴리곤 근사로 대체
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        rx, ry = abs(x2 - x1) / 2, abs(y2 - y1) / 2
        n = 64
        xs = [cx + rx * math.cos(2 * math.pi * i / n) for i in range(n + 1)]
        ys = [cy + ry * math.sin(2 * math.pi * i / n) for i in range(n + 1)]
        item = pg.PlotDataItem(x=xs, y=ys, pen=self._pen(self.COLOR_LINE, 1))
        self._p1.addItem(item)
        self._items.append(item)

    def _finish_text(self, x: float, y: float) -> None:
        from PyQt6.QtWidgets import QInputDialog
        import pyqtgraph as pg
        text, ok = QInputDialog.getText(None, "텍스트 입력", "내용:")
        if not ok or not text.strip():
            return
        item = pg.TextItem(text.strip(), color=self.COLOR_TEXT, anchor=(0, 1))
        item.setPos(x, y)
        self._p1.addItem(item)
        self._items.append(item)
