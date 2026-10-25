# core/subscription_ledger.py
# 소유자(패널 등)별 구독 ref-count 장부 — 순수 Python, Qt import 금지
#
# 용도
#   같은 종목을 여러 패널이 구독해도 피드에는 1회만 요청하고(first),
#   마지막 소유자가 놓을 때만 해제한다(last). 소유자별 건수 조회도 여기서.
#
#   ledger = SubscriptionLedger()
#   added, first = ledger.acquire("chart_1a2b", "AAPL", owner_type="chart")
#   if first: broker.subscribe_quote("AAPL")
#   for key, last in ledger.release_owner("chart_1a2b"):
#       if last: broker.unsubscribe_quote(key)
from __future__ import annotations

import threading
import time
from typing import Dict, Hashable, List, Set, Tuple


class SubscriptionLedger:
    """owner ↔ key 양방향 집계. 스레드 안전."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._owners:   Dict[Hashable, Set[str]] = {}
        self._by_owner: Dict[str, Set[Hashable]] = {}
        self._otype:    Dict[str, str] = {}

    def acquire(self, owner: str, key: Hashable,
                owner_type: str = "") -> Tuple[bool, bool]:
        """(added, first) — added: 이 소유자가 새로 보유, first: 아무도 보유하지 않던 키."""
        with self._lock:
            owners = self._owners.setdefault(key, set())
            first = not owners
            added = owner not in owners
            owners.add(owner)
            self._by_owner.setdefault(owner, set()).add(key)
            if owner_type:
                self._otype[owner] = owner_type
            return added, first

    def release(self, owner: str, key: Hashable) -> Tuple[bool, bool]:
        """(removed, last) — removed: 이 소유자가 보유 중이었음, last: 이제 보유자 없음."""
        with self._lock:
            return self._release_locked(owner, key)

    def release_owner(self, owner: str) -> List[Tuple[Hashable, bool]]:
        """소유자의 모든 키 해제 → [(key, last), ...]"""
        with self._lock:
            out = [(k, self._release_locked(owner, k)[1])
                   for k in list(self._by_owner.get(owner, ()))]
            self._by_owner.pop(owner, None)
            self._otype.pop(owner, None)
            return out

    def _release_locked(self, owner: str, key: Hashable) -> Tuple[bool, bool]:
        owners = self._owners.get(key)
        if not owners or owner not in owners:
            return False, False
        owners.discard(owner)
        held = self._by_owner.get(owner)
        if held is not None:
            held.discard(key)
            if not held:
                self._by_owner.pop(owner, None)
                self._otype.pop(owner, None)
        last = not owners
        if last:
            del self._owners[key]
        return True, last

    # ── 조회 ─────────────────────────────────────────────
    def keys(self) -> Set[Hashable]:
        with self._lock:
            return set(self._owners)

    def holders(self, key: Hashable) -> Set[str]:
        with self._lock:
            return set(self._owners.get(key, ()))

    def keys_of(self, owner: str) -> Set[Hashable]:
        with self._lock:
            return set(self._by_owner.get(owner, ()))

    def snapshot(self) -> dict:
        """{"panels": {owner: {type, total, items}}, "unique", "total_refs", "ts"}"""
        with self._lock:
            panels = {
                o: {"type":  self._otype.get(o, ""),
                    "total": len(ks),
                    "items": sorted(str(k) for k in ks)}
                for o, ks in self._by_owner.items()
            }
            return {
                "panels":     panels,
                "unique":     len(self._owners),
                "total_refs": sum(len(v) for v in self._owners.values()),
                "ts":         time.time(),
            }
