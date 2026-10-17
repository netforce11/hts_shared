# ui/layout_manager.py
# 키움 영웅문 스타일 레이아웃 매니저
# QMdiArea + QMdiSubWindow 기반 자유 배치

from __future__ import annotations
import json
import logging
from dataclasses import dataclass, asdict
from pathlib import Path

from PyQt6.QtWidgets import QMdiArea, QMdiSubWindow, QWidget
from PyQt6.QtCore import Qt, QRect

log = logging.getLogger(__name__)

GRID = 8   # 스냅 단위 (px)


@dataclass
class PanelGeometry:
    """패널 하나의 위치·크기·상태"""
    x: int = 0
    y: int = 0
    w: int = 400
    h: int = 300
    visible: bool = True
    maximized: bool = False


class PanelLayoutManager:
    """
    QMdiArea 위의 패널을 픽셀 단위로 관리.

    사용법:
        mgr = PanelLayoutManager(mdi_area, layout_path)
        sub = mgr.add(chart_panel)          # 패널 등록 → SubWindow 반환
        mgr.place("stock_chart", 0, 0, 800, 600)
        mgr.save()
        mgr.restore()
    """

    def __init__(self, mdi: QMdiArea, layout_path: Path) -> None:
        self._mdi  = mdi
        self._path = layout_path
        # panel_id → QMdiSubWindow
        self._windows: dict[str, QMdiSubWindow] = {}
        # panel_id → PanelGeometry (저장된 상태)
        self._geo: dict[str, PanelGeometry] = {}

    # ── 패널 등록 ─────────────────────────────────────────
    def add(self, panel: QWidget, *, title: str = "") -> QMdiSubWindow:
        """
        패널을 QMdiSubWindow에 embed하고 MdiArea에 추가.
        반환: QMdiSubWindow (직접 제어 필요 시 사용)
        """
        panel_id = getattr(panel, "PANEL_ID", id(panel))
        default_w, default_h = getattr(panel, "DEFAULT_SIZE", (400, 300))
        win_title = title or getattr(panel, "TITLE", panel_id)

        sub = QMdiSubWindow()
        sub.setWidget(panel)
        sub.setWindowTitle(win_title)
        sub.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        # 시스템 버튼 (최소화·최대화·닫기)
        sub.setSystemMenu(None)

        self._mdi.addSubWindow(sub)
        self._windows[panel_id] = sub

        # 저장된 geometry 있으면 적용, 없으면 기본값
        if panel_id in self._geo:
            self._apply_geo(panel_id)
        else:
            self._geo[panel_id] = PanelGeometry(w=default_w, h=default_h)
            sub.resize(default_w, default_h)

        return sub

    # ── 정밀 배치 ─────────────────────────────────────────
    def place(self, panel_id: str, x: int, y: int, w: int, h: int) -> None:
        """픽셀 단위 배치. 그리드 스냅 자동 적용."""
        x, y = self._snap(x, y)
        w, h = max(w, 80), max(h, 60)
        self._geo[panel_id] = PanelGeometry(x=x, y=y, w=w, h=h)
        self._apply_geo(panel_id)

    def show_panel(self, panel_id: str, visible: bool = True) -> None:
        sub = self._windows.get(panel_id)
        if sub:
            sub.setVisible(visible)
            if panel_id in self._geo:
                self._geo[panel_id].visible = visible

    def bring_to_front(self, panel_id: str) -> None:
        sub = self._windows.get(panel_id)
        if sub:
            self._mdi.setActiveSubWindow(sub)
            sub.raise_()

    # ── 저장 / 복원 ───────────────────────────────────────
    def save(self) -> None:
        """현재 모든 창의 geometry를 JSON에 저장"""
        # 저장 전 실제 위치/크기 수집
        for panel_id, sub in self._windows.items():
            if sub.isMaximized():
                geo = self._geo.setdefault(panel_id, PanelGeometry())
                geo.maximized = True
                geo.visible   = True
            else:
                r = sub.geometry()
                geo = PanelGeometry(
                    x=r.x(), y=r.y(), w=r.width(), h=r.height(),
                    visible=sub.isVisible(),
                    maximized=False,
                )
            self._geo[panel_id] = geo

        data = {pid: asdict(g) for pid, g in self._geo.items()}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        log.debug("Layout saved → %s", self._path)

    def restore(self) -> None:
        """JSON에서 geometry 로드 후 각 창에 적용"""
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text())
            self._geo = {
                pid: PanelGeometry(**v) for pid, v in raw.items()
            }
            for panel_id in self._windows:
                self._apply_geo(panel_id)
            log.debug("Layout restored ← %s", self._path)
        except Exception:
            log.warning("레이아웃 복원 실패", exc_info=True)

    # ── 내부 유틸 ─────────────────────────────────────────
    def _apply_geo(self, panel_id: str) -> None:
        sub = self._windows.get(panel_id)
        geo = self._geo.get(panel_id)
        if not sub or not geo:
            return
        if geo.maximized:
            sub.showMaximized()
        else:
            sub.setGeometry(QRect(geo.x, geo.y, geo.w, geo.h))
            sub.setVisible(geo.visible)

    @staticmethod
    def _snap(x: int, y: int) -> tuple[int, int]:
        """GRID px 단위로 스냅"""
        return (round(x / GRID) * GRID,
                round(y / GRID) * GRID)

    # ── 편의 프로퍼티 ─────────────────────────────────────
    @property
    def windows(self) -> dict[str, QMdiSubWindow]:
        return dict(self._windows)
