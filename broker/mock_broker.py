# broker/mock_broker.py
# 개발/테스트용 — 실제 브로커 없이 동작 보장

from __future__ import annotations
import uuid
import random
import threading
import logging
from ..core.order_validator import OrderRequest
from .base_broker import BaseBroker
from ..core.bus import DataBus
from ..core.topics import Topics

log = logging.getLogger(__name__)


class MockBroker(BaseBroker):
    def __init__(self, bus: DataBus) -> None:
        self._bus = bus
        self._positions: dict[str, int] = {}
        self._balance = 100_000.0
        self._feed_threads: dict[str, threading.Thread] = {}

    def connect(self) -> None:
        log.info("MockBroker connected")
        self._bus.publish(Topics.BROKER_CONNECTED, {"broker": "mock"})

    def disconnect(self) -> None:
        for sym in list(self._feed_threads):
            self.unsubscribe(sym)
        log.info("MockBroker disconnected")
        self._bus.publish(Topics.BROKER_DISCONNECTED, {"broker": "mock"})

    def subscribe(self, symbol: str) -> None:
        if symbol in self._feed_threads:
            return
        stop_evt = threading.Event()
        t = threading.Thread(
            target=self._fake_feed, args=(symbol, stop_evt),
            name=f"MockFeed-{symbol}", daemon=True
        )
        t.start()
        self._feed_threads[symbol] = (t, stop_evt)  # type: ignore
        log.debug("MockBroker: subscribed %s", symbol)

    def unsubscribe(self, symbol: str) -> None:
        if symbol not in self._feed_threads:
            return
        _t, stop_evt = self._feed_threads.pop(symbol)
        stop_evt.set()

    def place_order(self, req: OrderRequest) -> str:
        order_id = str(uuid.uuid4())[:8]
        log.info("MockBroker: order %s %s %s x%d", order_id, req.side, req.symbol, req.quantity)
        # 즉시 체결 시뮬레이션
        fill_price = round(random.uniform(100, 500), 2)
        self._bus.publish(Topics.order_fill(order_id), {
            "order_id": order_id, "symbol": req.symbol,
            "side": req.side, "qty": req.quantity, "price": fill_price
        })
        return order_id

    def cancel_order(self, order_id: str) -> None:
        log.info("MockBroker: cancel %s", order_id)

    def get_positions(self) -> dict:
        return dict(self._positions)

    def get_account(self) -> dict:
        return {"balance": self._balance, "currency": "USD"}

    # ── 스캐너 Mock ────────────────────────────────────────
    _MOCK_SCAN_POOLS = {
        "TOP_PERC_GAIN":   ["NVDA","TSLA","AMD","AAPL","META","AMZN","GOOGL","MSFT","NFLX","PLTR"],
        "TOP_PERC_LOSE":   ["BABA","NIO","RIVN","LCID","WISH","SNAP","TWTR","HOOD","COIN","SOFI"],
        "MOST_ACTIVE":     ["SPY","QQQ","AAPL","TSLA","NVDA","AMD","AMZN","MSFT","F","AAL"],
        "MOST_ACTIVE_USD": ["SPY","NVDA","AAPL","TSLA","MSFT","GOOGL","META","AMZN","AMD","NFLX"],
        "TOP_OPEN_PERC_GAIN": ["SMCI","MARA","RIOT","MSTR","CLSK","HUT","BTBT","CIFR","WULF","IREN"],
        "TOP_OPEN_PERC_LOSE": ["INTC","IBM","HPQ","T","VZ","CVS","WBA","KHC","PFE","MRK"],
        "HIGH_VS_13W_HL":  ["NVDA","META","GE","LLY","UNH","JPM","V","MA","AVGO","ORCL"],
        "LOW_VS_13W_HL":   ["BABA","NIO","PYPL","ETSY","RBLX","U","SNAP","LYFT","ABNB","UBER"],
    }

    def request_scanner(self, req_id: int, scan_code: str,
                        filters: dict | None = None) -> None:
        import time, random, threading
        def _mock():
            time.sleep(0.3)   # 조회 지연 시뮬레이션
            pool = self._MOCK_SCAN_POOLS.get(scan_code,
                   ["AAPL","MSFT","GOOGL","AMZN","NVDA"])
            results = []
            for rank, sym in enumerate(pool, 1):
                base = random.uniform(50, 600)
                chg  = random.uniform(-8, 8) if "LOSE" in scan_code else random.uniform(0.5, 12)
                if "LOSE" in scan_code:
                    chg = -abs(chg)
                results.append({
                    "rank":         rank,
                    "symbol":       sym,
                    "price":        round(base, 2),
                    "change":       round(base * chg / 100, 2),
                    "change_pct":   round(chg, 2),
                    "volume":       random.randint(1_000_000, 50_000_000),
                    "avg_volume":   random.randint(5_000_000, 30_000_000),
                    "market_cap":   round(random.uniform(1e9, 3e12), 0),
                    "exchange":     "NASDAQ",
                })
            self._bus.publish(Topics.SCANNER_RESULT, {
                "req_id":    req_id,
                "scan_code": scan_code,
                "results":   results,
                "ts":        time.time(),
            })
        threading.Thread(target=_mock, daemon=True).start()

    def cancel_scanner(self, req_id: int) -> None:
        pass  # Mock: 취소할 실체 없음

    # ── 가짜 시세 피드 ─────────────────────────────────────
    def _fake_feed(self, symbol: str, stop: threading.Event) -> None:
        import time
        price = random.uniform(100, 500)
        while not stop.is_set():
            price += random.gauss(0, 0.5)
            price = max(1.0, round(price, 2))
            bid = round(price - 0.01, 2)
            ask = round(price + 0.01, 2)
            self._bus.publish(Topics.stock_price(symbol), {
                "symbol": symbol, "price": price, "bid": bid, "ask": ask,
                "ts": time.time(),   # 레이턴시 측정용 Unix timestamp
            })
            self._bus.publish(Topics.stock_orderbook(symbol), {
                "symbol": symbol,
                "bids": [(bid, random.randint(100, 1000)) for _ in range(5)],
                "asks": [(ask, random.randint(100, 1000)) for _ in range(5)],
            })
            time.sleep(0.5)
