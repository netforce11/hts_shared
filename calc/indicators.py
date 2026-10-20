# calc/indicators.py
# 기술 지표 계산 (이동평균, RSI, 일목균형표 등) — calc_queue 전용 프로세스에서 실행

from __future__ import annotations
import collections
import math


class SMA:
    """단순 이동평균"""
    def __init__(self, period: int) -> None:
        self.period = period
        self._buf: collections.deque[float] = collections.deque(maxlen=period)

    def update(self, price: float) -> float | None:
        self._buf.append(price)
        if len(self._buf) < self.period:
            return None
        return sum(self._buf) / self.period


class EMA:
    """지수 이동평균"""
    def __init__(self, period: int) -> None:
        self.period = period
        self.k = 2 / (period + 1)
        self._ema: float | None = None
        self._count = 0

    def update(self, price: float) -> float | None:
        self._count += 1
        if self._count < self.period:
            self._ema = price if self._ema is None else (self._ema + price) / 2
            return None
        if self._count == self.period:
            self._ema = price
            return self._ema
        self._ema = price * self.k + self._ema * (1 - self.k)
        return round(self._ema, 4)


class RSI:
    """RSI (Relative Strength Index)"""
    def __init__(self, period: int = 14) -> None:
        self.period = period
        self._gains: collections.deque[float] = collections.deque(maxlen=period)
        self._losses: collections.deque[float] = collections.deque(maxlen=period)
        self._prev: float | None = None

    def update(self, price: float) -> float | None:
        if self._prev is None:
            self._prev = price
            return None
        delta = price - self._prev
        self._prev = price
        self._gains.append(max(delta, 0))
        self._losses.append(max(-delta, 0))
        if len(self._gains) < self.period:
            return None
        avg_gain = sum(self._gains) / self.period
        avg_loss = sum(self._losses) / self.period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return round(100 - (100 / (1 + rs)), 2)


class Ichimoku:
    """
    일목균형표 (Ichimoku Kinko Hyo) — 일봉 OHLC 기반.

    사용법:
        ichi = Ichimoku()
        for bar in daily_bars:          # bar: (high, low, close)
            result = ichi.update(bar)   # None 또는 dict 반환
    반환 dict 키:
        tenkan   전환선  (9일)
        kijun    기준선  (26일)
        spanA    선행스팬A (현재값; 26봉 앞에 그릴 것)
        spanB    선행스팬B (현재값; 26봉 앞에 그릴 것)
        chikou   후행스팬  (현재 종가; 26봉 뒤에 그릴 것)
    """

    TENKAN_P = 9
    KIJUN_P  = 26
    SPANB_P  = 52

    def __init__(self) -> None:
        self._highs: collections.deque[float] = collections.deque(maxlen=self.SPANB_P)
        self._lows:  collections.deque[float] = collections.deque(maxlen=self.SPANB_P)
        self._closes: list[float] = []

    def update(self, bar: tuple[float, float, float]) -> dict | None:
        """bar = (high, low, close)"""
        high, low, close = bar
        self._highs.append(high)
        self._lows.append(low)
        self._closes.append(close)

        if len(self._highs) < self.SPANB_P:
            return None

        def midpoint(period: int) -> float:
            hs = list(self._highs)[-period:]
            ls = list(self._lows)[-period:]
            return (max(hs) + min(ls)) / 2

        tenkan = midpoint(self.TENKAN_P)
        kijun  = midpoint(self.KIJUN_P)
        spanA  = (tenkan + kijun) / 2
        spanB  = midpoint(self.SPANB_P)
        chikou = close   # 26봉 뒤 위치는 차트에서 처리

        return {
            "tenkan": round(tenkan, 4),
            "kijun":  round(kijun,  4),
            "spanA":  round(spanA,  4),
            "spanB":  round(spanB,  4),
            "chikou": round(chikou, 4),
        }

    @staticmethod
    def calc_series(bars: list[tuple[float, float, float]]) -> list[dict | None]:
        """bars 전체에 대해 일목 시리즈 반환 (차트용)."""
        ichi = Ichimoku()
        return [ichi.update(b) for b in bars]
