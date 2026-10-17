# ui/panels/base_panel.py
# 모든 패널의 부모 — QWidget 기반 (QMdiSubWindow 안에 embed)
# 키움 영웅문 스타일: 자유 배치, 픽셀 정밀 이동/리사이즈

from __future__ import annotations
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt, QMetaObject, Q_ARG, pyqtSlot
from ...core.bus import DataBus


class BasePanel(QWidget):
    """
    상속 규칙:
      - PANEL_ID 반드시 오버라이드
      - 단축키 선언: register_shortcuts() 오버라이드
      - UI 콜백: 반드시 _invoke_main() 경유 (Qt 메인 스레드 보장)
      - 패널 닫기 시 bus.unsubscribe_all + 단축키 해제 자동 처리
    """

    PANEL_ID: str = "base"
    TITLE: str = "패널"
    DEFAULT_SIZE: tuple[int, int] = (400, 300)   # 기본 (w, h)

    def __init__(self, bus: DataBus, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bus = bus
        self._shortcut_mgr = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setObjectName(self.PANEL_ID)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        self._layout = layout

    # ── 단축키 선언 (각 패널에서 오버라이드) ──────────────
    def register_shortcuts(self) -> list[tuple[str, callable]]:
        return []

    def set_shortcut_manager(self, mgr) -> None:
        self._shortcut_mgr = mgr
        mgr.register_panel(self)

    # ── 포커스 → ShortcutManager 알림 ────────────────────
    def focusInEvent(self, event) -> None:
        if self._shortcut_mgr:
            self._shortcut_mgr.set_active(self)
        super().focusInEvent(event)

    # ── 스레드 안전 UI 콜백 ────────────────────────────────
    def _invoke_main(self, slot_name: str, data) -> None:
        QMetaObject.invokeMethod(
            self,
            slot_name,
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(object, data),
        )

    # ── 패널 종료 ──────────────────────────────────────────
    def closeEvent(self, event) -> None:
        self._cleanup()
        super().closeEvent(event)

    def _cleanup(self) -> None:
        self._bus.unsubscribe_all(self)
        if self._shortcut_mgr:
            self._shortcut_mgr.unregister_panel(self)
