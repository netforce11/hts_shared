# ui/chart/data_source.py
# Candle 구조체 + 추상 로더
# Tradier_Working2/ui/minute_chart/chart_data_source.py 기반
# 구체 구현(IBKR/Tradier)은 각 프로젝트에 위치

from __future__ import annotations
from abc      import abstractmethod
from datetime import date
from PyQt6.QtCore import QThread, pyqtSignal


# ── 공통 캔들 구조 ─────────────────────────────────────────
class Candle:
    """
    t: Unix timestamp (int)
    o, h, l, c: float
    v: int
    """
    __slots__ = ("t", "o", "h", "l", "c", "v")

    def __init__(self, t, o, h, l, c, v=0) -> None:
        self.t = int(t)
        self.o = float(o)
        self.h = float(h)
        self.l = float(l)
        self.c = float(c)
        self.v = int(v)

    def to_tuple(self) -> tuple:
        return (self.t, self.o, self.h, self.l, self.c, self.v)

    def __repr__(self) -> str:
        from datetime import datetime
        ts = datetime.fromtimestamp(self.t).strftime("%H:%M")
        return f"Candle({ts} o={self.o} h={self.h} l={self.l} c={self.c})"


# ── 추상 분봉 로더 ─────────────────────────────────────────
class BaseMinuteLoader(QThread):
    """
    각 프로젝트에서 상속 후 run() 구현.
    loaded → list[Candle]
    error  → 오류 메시지
    """
    loaded = pyqtSignal(list)
    error  = pyqtSignal(str)

    def __init__(self, symbol: str, target_date: date, parent=None) -> None:
        super().__init__(parent)
        self.symbol      = symbol
        self.target_date = target_date

    @abstractmethod
    def run(self) -> None: ...


# ── 추상 일봉 로더 ─────────────────────────────────────────
class BaseDailyLoader(QThread):
    """
    각 프로젝트에서 상속 후 run() 구현.
    """
    loaded = pyqtSignal(list)
    error  = pyqtSignal(str)

    def __init__(self, symbol: str, days: int = 60, parent=None) -> None:
        super().__init__(parent)
        self.symbol = symbol
        self.days   = days

    @abstractmethod
    def run(self) -> None: ...
