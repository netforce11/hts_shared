# ui/chart — 공통 차트 모듈

## 구성
- `data_source.py` — `Candle` 구조체, `BaseMinuteLoader`, `BaseDailyLoader` 추상 클래스
- `candle.py`      — `CandlestickItem` (pyqtgraph, PyQt6)
- `minute_chart_panel.py` — `MinuteChartPanel` 공통 패널

## 각 프로젝트에서 사용법

```python
# 1) 로더 구현 (프로젝트 내부)
from shared.ui.chart.data_source import BaseMinuteLoader, Candle

class IBKRMinuteLoader(BaseMinuteLoader):
    def run(self):
        # IBKR API 호출 → Candle 리스트 생성
        candles = [Candle(t, o, h, l, c, v), ...]
        self.loaded.emit(candles)


# 2) 패널 상속 (로더 주입)
from shared.ui.chart.minute_chart_panel import MinuteChartPanel

class StockChartPanel(MinuteChartPanel):
    def _make_minute_loader(self, symbol, target_date):
        return IBKRMinuteLoader(symbol, target_date)
```

## 단축키 (기본 제공)
| 키 | 동작 |
|----|------|
| `←` | 전날 |
| `→` | 다음날 |
| `F5` | 새로고침 |
