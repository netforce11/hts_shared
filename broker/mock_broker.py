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
        # 계좌 데이터 주기적 발행 (5초 간격)
        self._acct_stop = threading.Event()
        self._acct_thread = threading.Thread(
            target=self._fake_account_feed,
            name="MockAccount",
            daemon=True,
        )
        self._acct_thread.start()

    def disconnect(self) -> None:
        for sym in list(self._feed_threads):
            self.unsubscribe(sym)
        if hasattr(self, "_acct_stop"):
            self._acct_stop.set()
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
        fill_price  = round(random.uniform(100, 500), 2)
        commission  = round(req.quantity * 0.005, 4)   # $0.005/주 모의 수수료
        fill_id     = str(uuid.uuid4())[:12]

        # 실현손익: SELL 시 단순 계산 (Mock이므로 avg_cost 없이 랜덤)
        realized_pnl = 0.0
        if req.side == "SELL":
            avg_cost = round(fill_price * random.uniform(0.95, 1.05), 2)
            realized_pnl = round((fill_price - avg_cost) * req.quantity - commission, 2)

        fill_payload = {
            "fill_id":      fill_id,
            "order_id":     order_id,
            "symbol":       req.symbol,
            "side":         req.side,
            "qty":          req.quantity,
            "fill_price":   fill_price,
            "price":        fill_price,   # 하위 호환
            "commission":   commission,
            "realized_pnl": realized_pnl,
        }

        # order.fill.{id} — 개별 주문 구독용 (기존 호환)
        self._bus.publish(Topics.order_fill(order_id), fill_payload)

        # order.filled — DB 저장 + 체결패널용 (집계 토픽)
        self._bus.publish(Topics.ORDER_FILLED, fill_payload)

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

    # ── 가짜 계좌 피드 ─────────────────────────────────────
    def _fake_account_feed(self) -> None:
        """5초 간격으로 모의 계좌 데이터 발행."""
        import time
        net_liq       = 125_000.0
        cash          = 80_000.0
        unrealized    = 2_500.0
        realized      = 800.0
        maint_margin  = 12_000.0
        init_margin   = 15_000.0
        drift         = 0.0   # 누적 일일 손익 드리프트

        # Step4(_build_panels) 완료까지 대기 후 최초 발행
        # — connect()는 Step2에서 호출되고 패널은 Step4에서 구독하므로
        #   즉시 발행하면 구독자가 없어 소실됨 → 2초 지연
        time.sleep(2.0)
        self._publish_account(net_liq, cash, unrealized, realized,
                              maint_margin, init_margin, drift)
        while not self._acct_stop.is_set():
            time.sleep(5)
            # 소폭 변동 시뮬레이션
            unrealized  = round(unrealized + random.gauss(0, 120), 2)
            net_liq     = round(cash + unrealized + random.gauss(0, 50), 2)
            drift       = round(drift + random.gauss(0, 30), 2)
            realized    = round(realized + random.gauss(0, 20), 2)
            maint_margin = round(abs(unrealized) * 0.15 + random.uniform(0, 500), 2)
            self._publish_account(net_liq, cash, unrealized, realized,
                                  maint_margin, init_margin, drift)

    def _publish_account(
        self,
        net_liq: float, cash: float,
        unrealized: float, realized: float,
        maint_margin: float, init_margin: float,
        drift: float,
    ) -> None:
        buying_power   = round(cash * 2, 2)          # Reg-T 2배
        avail          = round(max(cash - maint_margin, 0), 2)
        excess_liq     = round(net_liq - maint_margin, 2)
        daily_pnl      = round(unrealized + realized + drift, 2)
        self._bus.publish(Topics.ACCOUNT_UPDATE, {
            "net_liquidation":    net_liq,
            "cash_balance":       cash,
            "buying_power":       buying_power,
            "available_funds":    avail,
            "excess_liquidity":   excess_liq,
            "maintenance_margin": maint_margin,
            "initial_margin":     init_margin,
            "unrealized_pnl":     unrealized,
            "realized_pnl":       realized,
            "daily_pnl":          daily_pnl,
            "currency":           "USD",
            "account_id":         "MOCK-U123456",
        })
        # RISK_DAILY_PNL 도 동시에 갱신
        self._bus.publish(Topics.RISK_DAILY_PNL, {"daily_pnl": daily_pnl})

    # ── 가짜 시세 피드 ─────────────────────────────────────
    def _fake_feed(self, symbol: str, stop: threading.Event) -> None:
        import time
        price = random.uniform(100, 500)
        # prev_close: 초기 가격에서 ±2% 범위의 전일 종가 시뮬레이션
        prev_close = round(price * random.uniform(0.98, 1.02), 2)
        while not stop.is_set():
            price += random.gauss(0, 0.5)
            price = max(1.0, round(price, 2))
            bid = round(price - 0.01, 2)
            ask = round(price + 0.01, 2)
            self._bus.publish(Topics.stock_price(symbol), {
                "symbol": symbol, "price": price, "bid": bid, "ask": ask,
                "prev_close": prev_close,
                "ts": time.time(),   # 레이턴시 측정용 Unix timestamp
            })
            self._bus.publish(Topics.stock_orderbook(symbol), {
                "symbol": symbol,
                "bids": [(bid, random.randint(100, 1000)) for _ in range(5)],
                "asks": [(ask, random.randint(100, 1000)) for _ in range(5)],
            })
            time.sleep(0.5)
