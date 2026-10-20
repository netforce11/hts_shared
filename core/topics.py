# core/topics.py
# 토픽 네이밍: "레이어.대상.세부" 형식
# 문자열 하드코딩 금지 — 반드시 Topics 정적 메서드 사용


class Topics:
    # ── 시장 데이터 ──────────────────────────────────────
    @staticmethod
    def stock_price(symbol: str) -> str:
        return f"stock.price.{symbol}"

    @staticmethod
    def stock_orderbook(symbol: str) -> str:
        return f"stock.orderbook.{symbol}"

    @staticmethod
    def stock_trade(symbol: str) -> str:
        return f"stock.trade.{symbol}"

    # ── 지표 (이동평균/RSI 등) ────────────────────────────
    @staticmethod
    def indicator(symbol: str, name: str) -> str:
        return f"indicator.{name}.{symbol}"

    # ── 주문/체결 ─────────────────────────────────────────
    @staticmethod
    def order_status(order_id: str) -> str:
        return f"order.status.{order_id}"

    @staticmethod
    def order_fill(order_id: str) -> str:
        return f"order.fill.{order_id}"

    # ── 포지션/잔고 ───────────────────────────────────────
    @staticmethod
    def portfolio_position(symbol: str) -> str:
        return f"portfolio.position.{symbol}"

    PORTFOLIO_SUMMARY = "portfolio.summary"
    ACCOUNT_BALANCE   = "account.balance"

    # 계좌 전체 정보 갱신 (AccountPanel 전용)
    # payload 키:
    #   net_liquidation   : float  — 총 자산
    #   cash_balance      : float  — 현금 잔고
    #   buying_power      : float  — 매수 가능 금액
    #   available_funds   : float  — 사용 가능 자금
    #   excess_liquidity  : float  — 초과 유동성
    #   maintenance_margin: float  — 유지 마진
    #   initial_margin    : float  — 초기 마진
    #   unrealized_pnl    : float  — 미실현 손익
    #   realized_pnl      : float  — 실현 손익 (당일)
    #   daily_pnl         : float  — 일일 손익 (unrealized+realized)
    #   currency          : str    — 통화 (기본 "USD")
    #   account_id        : str    — 계좌번호 (선택)
    ACCOUNT_UPDATE = "account.update"

    # ── 리스크 ───────────────────────────────────────────
    RISK_KILL_SWITCH   = "risk.kill_switch"
    RISK_DAILY_PNL     = "risk.daily_pnl"
    RISK_WARNING       = "risk.warning"

    # ── 시스템 ───────────────────────────────────────────
    SYSTEM_STATUS       = "system.status"
    SYSTEM_ERROR        = "system.error"
    BROKER_CONNECTED    = "broker.connected"
    BROKER_DISCONNECTED = "broker.disconnected"

    # ── 주문/DB 이벤트 ────────────────────────────────────
    ORDER_PLACED    = "order.placed"
    ORDER_FILLED    = "order.filled"
    ORDER_CANCELLED = "order.cancelled"

    # ── 관심종목 ──────────────────────────────────────────
    # 관심종목 클릭 시 → 모든 패널이 이 토픽으로 종목 전환
    WATCHLIST_SELECT = "watchlist.symbol_selected"

    # ── 차트 외부 제어 ────────────────────────────────────
    # 외부 캘린더(관심종목 패널 하단 등)에서 날짜 클릭 →
    # 차트 패널이 이 토픽을 구독하여 분봉 날짜 전환
    # payload: {"date": "YYYY-MM-DD"} 또는 datetime.date 객체
    CHART_DATE_SELECT = "chart.date.select"

    # 차트 심볼 외부 전환 (관심종목 클릭 → 차트 자동 전환용)
    # payload: {"symbol": "AAPL"}
    CHART_SYMBOL_SELECT = "chart.symbol.select"

    # ── 스캐너 ────────────────────────────────────────────
    SCANNER_RESULT   = "scanner.result"   # 스캔 결과 도착
    SCANNER_ERROR    = "scanner.error"    # 스캔 오류
