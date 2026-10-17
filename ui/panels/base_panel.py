# ui/panels/base_panel.py
# 모든 패널의 부모 — QWidget 기반 (QMdiSubWindow 안에 embed)
# 기본 탑재 단축키:
#   Alt+=  패널 넓게  (QMdiSubWindow 리사이즈)
#   Alt+-  패널 좁게
#   Alt+]  폰트 크게
#   Alt+[  폰트 작게

from __future__ import annotations
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QMdiSubWindow, QApplication
from PyQt6.QtCore import Qt, QMetaObject, Q_ARG, pyqtSlot
from PyQt6.QtGui import QFont, QKeySequence, QShortcut
from ...core.bus import DataBus

_FONT_MIN = 7
_FONT_MAX = 22
_PANEL_STEP = 40   # px 단위 resize 폭


class BasePanel(QWidget):
    """
    상속 규칙:
      - PANEL_ID, TITLE, DEFAULT_SIZE 오버라이드
      - 단축키 추가: register_shortcuts() 오버라이드 후 super() 호출
      - UI 콜백: 반드시 _invoke_main() 경유
      - 패널 종료 시 bus.unsubscribe_all + 단축키 해제 자동 처리
    """

    PANEL_ID: str = "base"
    TITLE: str = "패널"
    DEFAULT_SIZE: tuple[int, int] = (400, 300)

    def __init__(self, bus: DataBus, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bus = bus
        self._shortcut_mgr = None
        self._font_size: int = 10
        self._shortcuts: list[QShortcut] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setObjectName(self.PANEL_ID)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        self._layout = layout

    # ── 단축키 등록 ────────────────────────────────────────
    def register_shortcuts(self) -> list[tuple[str, callable]]:
        """
        서브클래스에서 오버라이드 시 반드시 super() 포함:
            return super().register_shortcuts() + [("F1", self.my_fn)]
        """
        return [
            ("Alt+=", self._panel_wider),    # 패널 넓게
            ("Alt+-", self._panel_narrower), # 패널 좁게
            ("Alt+]", self._font_up),        # 폰트 크게
            ("Alt+[", self._font_down),      # 폰트 작게
        ]

    def set_shortcut_manager(self, mgr) -> None:
        self._shortcut_mgr = mgr
        mgr.register_panel(self)

    def _install_shortcuts(self) -> None:
        """ShortcutManager가 호출 — 이 패널이 활성화될 때 단축키 활성화"""
        for key, fn in self.register_shortcuts():
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)
            self._shortcuts.append(sc)

    def _remove_shortcuts(self) -> None:
        for sc in self._shortcuts:
            sc.setEnabled(False)
            sc.deleteLater()
        self._shortcuts.clear()

    # ── 포커스 → ShortcutManager 알림 ────────────────────
    def focusInEvent(self, event) -> None:
        if self._shortcut_mgr:
            self._shortcut_mgr.set_active(self)
        super().focusInEvent(event)

    # ── 패널 크기 조절 (Alt+= / Alt+-) ───────────────────
    def _sub_window(self) -> QMdiSubWindow | None:
        p = self.parent()
        while p:
            if isinstance(p, QMdiSubWindow):
                return p
            p = p.parent()
        return None

    def _panel_wider(self) -> None:
        sub = self._sub_window()
        if sub:
            sub.resize(sub.width() + _PANEL_STEP, sub.height())

    def _panel_narrower(self) -> None:
        sub = self._sub_window()
        if sub:
            sub.resize(max(sub.width() - _PANEL_STEP, 120), sub.height())

    # ── 폰트 크기 조절 (Alt+] / Alt+[) ───────────────────
    def _font_up(self) -> None:
        if self._font_size < _FONT_MAX:
            self._font_size += 1
            self._apply_font()

    def _font_down(self) -> None:
        if self._font_size > _FONT_MIN:
            self._font_size -= 1
            self._apply_font()

    def _apply_font(self) -> None:
        """자신과 모든 자식 위젯에 폰트 적용"""
        font = QFont()
        font.setPointSize(self._font_size)
        self.setFont(font)
        for child in self.findChildren(QWidget):
            child.setFont(font)

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
        self._remove_shortcuts()
        if self._shortcut_mgr:
            self._shortcut_mgr.unregister_panel(self)
