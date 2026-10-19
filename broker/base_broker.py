# broker/base_broker.py
# 브로커 추상 인터페이스 — IBKR / Mock 전부 동일 API

from __future__ import annotations
from abc import ABC, abstractmethod
from ..core.order_validator import OrderRequest


class BaseBroker(ABC):

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def subscribe(self, symbol: str) -> None:
        """실시간 시세 구독"""
        ...

    @abstractmethod
    def unsubscribe(self, symbol: str) -> None: ...

    @abstractmethod
    def place_order(self, req: OrderRequest) -> str:
        """주문 발주 → order_id 반환"""
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> None: ...

    @abstractmethod
    def get_positions(self) -> dict: ...

    @abstractmethod
    def get_account(self) -> dict: ...

    # ── 스캐너 (선택 구현 — 미구현 시 빈 동작) ──────────
    def request_scanner(self, req_id: int, scan_code: str,
                        filters: dict | None = None) -> None:
        """
        시장 스캐너 조회 요청.
        결과는 DataBus Topics.SCANNER_RESULT 로 publish됨.
        filters 예: {"min_price": 5.0, "max_price": 500.0,
                     "above_volume": 500000, "market": "STK"}
        """

    def cancel_scanner(self, req_id: int) -> None:
        """스캐너 구독 취소"""
