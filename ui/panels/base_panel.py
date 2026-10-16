# ui/panels/base_panel.py
# 모든 패널의 부모 — 헤더/테마/DataBus 구독 + 단축키 생명주기 자동 관리

from __future__ import annotations
from PyQt6.QtWidgets import QDockWidget, QWidget, QVBoxLayout
from PyQt6.QtCore import Qt, QMetaObject, Q_ARG, pyqtSlot
from ...core.bus import DataBus


class BasePanel(QDockWidget):
    """
    상속 규칙:
      - PANEL_ID 반드시 오버라이드
      - 단축키 선언: register_shortcuts() 오버라이드
      - UI 콜백: 반드시 _invoke_main() 경유 (Qt 메인 스레드 보장)
      - 패널 닫기 시 bus.unsubscribe_all + 단축키 해제 자동 처리
    """

    PANEL_ID: str = "base"

    def __init__(
        self,
        title: str,
        bus: DataBus,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(title, parent)
        self._bus = bus
        self._shortcut_mgr = None   # MainWindow에서 set_shortcut_manager() 호출
        self._setup_ui()
        self.visibilityChanged.connect(self._on_visibility_changed)

    def _setup_ui(self) -> None:
        self.setObjectName(self.PANEL_ID)
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable |
            QDockWidget.DockWidgetFeature.DockWidgetFloatable |
            QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        container = QWidget()
        self._layout = QVBoxLayout(container)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self.setWidget(container)

    # ── 단축키 선언 (각 패널에서 오버라이드) ──────────────
    def register_shortcuts(self) -> list[tuple[str, callable]]:
        """
        반환 형식: [("F1", self.some_method), ("Ctrl+B", self.buy), ...]
        빈 리스트 반환 시 단축키 없음.
        """
        return []

    def set_shortcut_manager(self, mgr) -> None:
        """MainWindow가 패널 생성 후 즉시 호출"""
        self._shortcut_mgr = mgr
        mgr.register_panel(self)

    # ── 포커스 인/아웃 → ShortcutManager에 알림 ──────────
    def focusInEvent(self, event) -> None:
        if self._shortcut_mgr:
            self._shortcut_mgr.set_active(self)
        super().focusInEvent(event)

    # ── 스레드 안전 UI 콜백 ────────────────────────────────
    def _invoke_main(self, slot_name: str, data) -> None:
        """Core 스레드 → Qt 메인 스레드로 안전하게 전달"""
        QMetaObject.invokeMethod(
            self,
            slot_name,
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(object, data),
        )

    # ── 패널 닫기/숨기기 ──────────────────────────────────
    def _on_visibility_changed(self, visible: bool) -> None:
        if not visible:
            self._cleanup()

    def closeEvent(self, event) -> None:
        self._cleanup()
        super().closeEvent(event)

    def _cleanup(self) -> None:
        self._bus.unsubscribe_all(self)
        if self._shortcut_mgr:
            self._shortcut_mgr.unregister_panel(self)
