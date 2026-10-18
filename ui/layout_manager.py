"""
shared/ui/layout_manager.py
QMdiArea 기반 패널 레이아웃 매니저

기능:
  - 8px 그리드 스냅
  - 레이아웃 JSON 저장/복원
  - 패널 show/hide / bring_to_front
  - 탭 그룹: 여러 패널을 QTabWidget 창으로 묶기 / 분리
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional

from PyQt6.QtWidgets import (
    QMdiArea, QMdiSubWindow, QWidget,
    QTabWidget, QVBoxLayout,
)
from PyQt6.QtCore import Qt, QRect, pyqtSignal

log = logging.getLogger(__name__)

GRID = 8


def _snap(v: int) -> int:
    return round(v / GRID) * GRID


@dataclass
class PanelGeometry:
    x: int = 0
    y: int = 0
    w: int = 400
    h: int = 300
    visible: bool = True
    maximized: bool = False


# ─────────────────────────────────────────────────────────
# 탭 그룹 서브윈도우
# ─────────────────────────────────────────────────────────
class TabGroupSubWindow(QMdiSubWindow):
    """여러 패널을 탭으로 묶는 MDI 서브윈도우."""
    tab_detached = pyqtSignal(str)   # 분리된 panel_id

    def __init__(self, group_id: str, parent=None):
        super().__init__(parent)
        self.group_id = group_id
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        self._tab = QTabWidget()
        self._tab.setTabsClosable(True)
        self._tab.setMovable(True)
        self._tab.tabCloseRequested.connect(self._on_tab_close)
        self._tab.setStyleSheet(
            "QTabWidget::pane { border:1px solid #D0D7DE; }"
            "QTabBar::tab { padding:4px 10px; min-width:60px; font-size:12px; }"
            "QTabBar::tab:selected { background:#0969DA; color:#fff;"
            "  border-bottom:2px solid #0969DA; }"
            "QTabBar::tab:!selected { background:#F6F8FA; color:#444; }"
            "QTabBar::tab:hover { background:#EAF0FB; }"
        )
        container = QWidget()
        lay = QVBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._tab)
        self.setWidget(container)
        self._pid_map: dict[str, QWidget] = {}

    def add_panel(self, pid: str, widget: QWidget, title: str) -> None:
        if pid in self._pid_map:
            return
        self._pid_map[pid] = widget
        self._tab.addTab(widget, title)

    def remove_panel(self, pid: str) -> Optional[QWidget]:
        widget = self._pid_map.pop(pid, None)
        if widget is None:
            return None
        idx = self._tab.indexOf(widget)
        if idx >= 0:
            self._tab.removeTab(idx)
        return widget

    def panel_ids(self) -> list[str]:
        return list(self._pid_map.keys())

    def _on_tab_close(self, idx: int) -> None:
        widget = self._tab.widget(idx)
        pid = next((p for p, w in self._pid_map.items() if w is widget), None)
        if pid:
            self.remove_panel(pid)
            self.tab_detached.emit(pid)
        if self._tab.count() == 0:
            self.hide()


# ─────────────────────────────────────────────────────────
# 메인 레이아웃 매니저
# ─────────────────────────────────────────────────────────
class PanelLayoutManager:
    """
    QMdiArea 위에 패널(QWidget)을 QMdiSubWindow로 감싸 관리.

    사용법:
        mgr = PanelLayoutManager(mdi, Path("layout.json"))
        mgr.add(panel, "호가창")
        mgr.place("orderbook", 0, 0, 320, 600)
        mgr.save()
        mgr.restore()
    """

    def __init__(self, mdi: QMdiArea, layout_file: Path) -> None:
        self._mdi  = mdi
        self._file = Path(layout_file)
        self._subs: Dict[str, QMdiSubWindow] = {}
        self._geom: Dict[str, PanelGeometry] = {}

    # ── 패널 추가 ────────────────────────────────────────
    def add(self, panel: QWidget, title: str = "",
            panel_id: Optional[str] = None) -> QMdiSubWindow:
        pid = panel_id or str(getattr(panel, "PANEL_ID", id(panel)))
        sub = QMdiSubWindow()
        sub.setWidget(panel)
        sub.setWindowTitle(title or getattr(panel, "TITLE", str(pid)))
        sub.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        w, h = getattr(panel, "DEFAULT_SIZE", (400, 300))
        sub.resize(w, h)
        self._mdi.addSubWindow(sub)
        self._subs[pid] = sub
        sub.hide()   # 기본값: 숨김 — restore() 또는 place()에서 표시
        return sub

    # ── 배치 (그리드 스냅) ──────────────────────────────
    def place(self, panel_id: str,
              x: int, y: int, w: int, h: int) -> None:
        sub = self._subs.get(panel_id)
        if not sub:
            log.warning("place: 패널 '%s' 없음", panel_id)
            return
        sub.setGeometry(QRect(_snap(x), _snap(y), _snap(w), _snap(h)))
        sub.show()

    # ── 표시/숨김 ───────────────────────────────────────
    def show_panel(self, panel_id: str, visible: bool) -> None:
        sub = self._subs.get(panel_id)
        if sub:
            sub.setVisible(visible)

    # ── 전체 숨김 ───────────────────────────────────────
    def hide_all(self) -> None:
        """모든 패널(탭 그룹 포함)을 숨긴다."""
        for sub in self._subs.values():
            sub.hide()

    # ── 최상위로 ────────────────────────────────────────
    def bring_to_front(self, panel_id: str) -> None:
        sub = self._subs.get(panel_id)
        if sub:
            sub.setVisible(True)
            self._mdi.setActiveSubWindow(sub)
            sub.raise_()

    # ── 탭 그룹 생성 ────────────────────────────────────
    def create_tab_group(self, panel_ids: List[str],
                         x: int = 100, y: int = 100,
                         w: int = 600, h: int = 500) -> Optional[str]:
        """panel_ids의 패널들을 탭 그룹으로 묶는다."""
        group_id = f"__tabgroup_{uuid.uuid4().hex[:6]}"
        tab_win = TabGroupSubWindow(group_id)
        tab_win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        for pid in panel_ids:
            sub = self._subs.get(pid)
            if not sub:
                continue
            widget = sub.widget()
            if widget is None:
                continue
            title = sub.windowTitle()
            sub.hide()
            sub.setWidget(None)
            tab_win.add_panel(pid, widget, title)

        def _on_detach(pid: str, gid: str = group_id) -> None:
            self._detach_from_group(pid, gid)

        tab_win.tab_detached.connect(_on_detach)
        tab_win.setWindowTitle("탭 그룹")
        tab_win.resize(_snap(w), _snap(h))
        self._mdi.addSubWindow(tab_win)
        tab_win.setGeometry(QRect(_snap(x), _snap(y), _snap(w), _snap(h)))
        tab_win.show()
        self._subs[group_id] = tab_win
        return group_id

    def _detach_from_group(self, pid: str, group_id: str) -> None:
        tab_win = self._subs.get(group_id)
        if not isinstance(tab_win, TabGroupSubWindow):
            return
        widget = tab_win._pid_map.get(pid)
        if widget is None:
            return
        tab_win.remove_panel(pid)
        sub = self._subs.get(pid)
        if sub:
            sub.setWidget(widget)
            r = tab_win.geometry()
            sub.setGeometry(QRect(r.x() + 40, r.y() + 40, r.width(), r.height()))
            sub.show()
            self._mdi.setActiveSubWindow(sub)
        if tab_win._tab.count() == 0:
            tab_win.hide()

    def _clear_all_tab_groups(self) -> None:
        group_ids = [gid for gid, sub in self._subs.items()
                     if isinstance(sub, TabGroupSubWindow)]
        for gid in group_ids:
            tab_win: TabGroupSubWindow = self._subs[gid]
            for pid in list(tab_win.panel_ids()):
                widget = tab_win.remove_panel(pid)
                sub = self._subs.get(pid)
                if sub and widget:
                    sub.setWidget(widget)
                    sub.hide()
            self._mdi.removeSubWindow(tab_win)
            tab_win.deleteLater()
            del self._subs[gid]

    # ── 저장 ────────────────────────────────────────────
    def save(self, file: Optional[Path] = None) -> None:
        target = Path(file) if file else self._file
        data: dict = {}
        tab_groups: list = []

        for pid, sub in self._subs.items():
            r = sub.geometry()
            if isinstance(sub, TabGroupSubWindow):
                tab_groups.append({
                    "group_id": sub.group_id,
                    "pids":     sub.panel_ids(),
                    "x": r.x(), "y": r.y(),
                    "w": r.width(), "h": r.height(),
                    "visible": sub.isVisible(),
                })
            else:
                data[pid] = asdict(PanelGeometry(
                    x=r.x(), y=r.y(), w=r.width(), h=r.height(),
                    visible=sub.isVisible(),
                    maximized=sub.isMaximized(),
                ))

        payload = {"panels": data, "tab_groups": tab_groups}
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
            log.debug("레이아웃 저장: %s", target)
        except Exception:
            log.exception("레이아웃 저장 실패")

    # ── 복원 ────────────────────────────────────────────
    def restore(self, file: Optional[Path] = None) -> bool:
        target = Path(file) if file else self._file
        if not target.exists():
            return False
        try:
            payload = json.loads(target.read_text())
        except Exception:
            log.exception("레이아웃 파일 읽기 실패")
            return False

        self._clear_all_tab_groups()

        if "panels" not in payload:
            data, tab_groups = payload, []
        else:
            data       = payload.get("panels", {})
            tab_groups = payload.get("tab_groups", [])

        for sub in self._subs.values():
            if not isinstance(sub, TabGroupSubWindow):
                sub.hide()

        for pid, raw in data.items():
            sub = self._subs.get(pid)
            if not sub:
                continue
            g = PanelGeometry(**raw)
            sub.setGeometry(QRect(_snap(g.x), _snap(g.y),
                                  _snap(g.w), _snap(g.h)))
            sub.setVisible(g.visible)
            if g.maximized:
                sub.showMaximized()

        for tg in tab_groups:
            pids = [p for p in tg.get("pids", []) if p in self._subs]
            if len(pids) < 1:
                continue
            self.create_tab_group(
                pids,
                x=tg.get("x", 100), y=tg.get("y", 100),
                w=tg.get("w", 600), h=tg.get("h", 450),
            )

        log.debug("레이아웃 복원: %s", target)
        return True
