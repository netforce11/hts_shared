"""SubscriptionLedger 테스트 — python3 -m pytest 또는 직접 실행"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.subscription_ledger import SubscriptionLedger


def test_first_and_last():
    L = SubscriptionLedger()
    assert L.acquire("A", "AAPL") == (True, True)
    assert L.acquire("B", "AAPL") == (True, False)     # 공유 → 피드 재요청 불필요
    assert L.acquire("A", "AAPL") == (False, False)    # 중복 무해
    assert L.release("A", "AAPL") == (True, False)     # B 가 아직 보유
    assert L.release("B", "AAPL") == (True, True)      # 마지막 → 피드 해제
    assert L.release("B", "AAPL") == (False, False)
    assert L.keys() == set()


def test_release_owner_and_snapshot():
    L = SubscriptionLedger()
    L.acquire("chart_1", "AAPL", "chart")
    L.acquire("chart_1", "TSLA", "chart")
    L.acquire("wl_1", "AAPL", "watchlist")
    snap = L.snapshot()
    assert snap["unique"] == 2 and snap["total_refs"] == 3
    assert snap["panels"]["chart_1"] == {"type": "chart", "total": 2, "items": ["AAPL", "TSLA"]}
    out = dict(L.release_owner("chart_1"))
    assert out == {"AAPL": False, "TSLA": True}
    assert L.release_owner("chart_1") == []            # 중복 호출 무해
    assert set(L.snapshot()["panels"]) == {"wl_1"}
    assert L.holders("AAPL") == {"wl_1"} and L.keys_of("wl_1") == {"AAPL"}


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("PASS", n)
