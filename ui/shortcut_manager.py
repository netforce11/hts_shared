# ui/shortcut_manager.py
# 패널별 단축키 관리 — 활성 패널의 단축키만 활성화

from __future__ import annotations
import logging
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget

log = logging.getLogger(__name__)


class ShortcutManager:
    """
    패널별 단축키 관리 — 포커스를 받은 패널의 단축키만 활성화.

    동작 흐름:
      1. panel.set_shortcut_manager(mgr) 호출
         → mgr.register_panel(panel) 내부 호출
         → register_shortcuts() 읽어 QShortcut 생성 (비활성 상태)
      2. 패널 클릭/포커스 → BasePanel.focusInEvent
         → mgr.set_active(panel)
         → 이전 패널 단축키 disabled, 현재 패널 단축키 enabled
      3. 패널 닫힘 → BasePanel._cleanup → mgr.unregister_panel
         → QShortcut 완전 제거

    같은 키(예: Alt+=)를 모든 패널이 가져도 충돌 없음.
    MainWindow에서 하나만 생성.
    """

    def __init__(self, main_window: QWidget) -> None:
        self._win = main_window
        self._active_panel = None
        # panel_id → [QShortcut, ...]
        self._shortcuts: dict[str, list[QShortcut]] = {}

    # ── 패널 등록 ─────────────────────────────────────────
    def register_panel(self, panel) -> None:
        """
        BasePanel.register_shortcuts() 반환값을 읽어 QShortcut 생성.
        처음엔 비활성화 상태로 등록.
        """
        panel_id = panel.PANEL_ID
        bindings = panel.register_shortcuts()
        if not bindings:
            return

        shortcuts = []
        for key_str, callback in bindings:
            sc = QShortcut(QKeySequence(key_str), self._win)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(callback)
            sc.setEnabled(False)   # 비활성 상태로 시작
            shortcuts.append(sc)
            log.debug("Registered shortcut [%s] %s → %s", panel_id, key_str, callback.__name__)

        self._shortcuts[panel_id] = shortcuts

    def unregister_panel(self, panel) -> None:
        """패널 닫힐 때 단축키 완전 제거"""
        panel_id = panel.PANEL_ID
        for sc in self._shortcuts.pop(panel_id, []):
            sc.setEnabled(False)
            sc.deleteLater()

    # ── 활성 패널 전환 ────────────────────────────────────
    def set_active(self, panel) -> None:
        """패널 포커스 인 시 호출"""
        # 이전 패널 단축키 비활성화
        if self._active_panel and self._active_panel is not panel:
            prev_id = self._active_panel.PANEL_ID
            for sc in self._shortcuts.get(prev_id, []):
                sc.setEnabled(False)

        # 새 패널 단축키 활성화
        self._active_panel = panel
        for sc in self._shortcuts.get(panel.PANEL_ID, []):
            sc.setEnabled(True)

        log.debug("Active panel shortcuts: %s", panel.PANEL_ID)
