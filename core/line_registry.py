# core/line_registry.py
# IBKR 시장데이터 라인(reqMktData) 집계 + 앱 간 합산
#
# 배경
#   IBKR 의 시세 라인 한도(기본 100)는 "앱/클라이언트 단위"가 아니라 "계정 단위 공유 풀"이다.
#   앱마다 자기 구독만 세면 두 앱을 같이 켰을 때 합계가 보이지 않는다.
#
# 동작
#   - 앱 안: reqMktData 직전 try_reserve(), cancel 때 release() — 락 안에서 한도 검사+등록(경쟁 조건 방지)
#   - 앱 간: 각 프로세스가 자기 라인 수를 JSON 파일(하트비트 포함)로 공유 폴더에 기록하고
#            다른 프로세스 파일을 읽어 합산한다. 하트비트가 끊기거나 PID 가 죽은 파일은 무시.
#   - 같은 PC 에서 도는 앱끼리만 합산한다(다른 PC/다른 계정 사용분은 알 수 없음).
#
# 정본: hts_shared/core/line_registry.py
#       (Tradier_Working2 는 core/feed/line_registry.py 에 동일 사본 — 파일 포맷이 계약이므로 서로 호환)
from __future__ import annotations

import atexit
import glob
import json
import os
import sys
import threading
import time
from typing import Callable, Dict, Hashable, Optional

DEFAULT_LIMIT = 95            # IBKR 기본 100 − 안전 여유 5
DEFAULT_DIR   = os.path.join(os.path.expanduser("~"), ".hts_ibkr_lines")

# 라인을 점유하지 못한 요청(거절/없는 종목/미구독)에 해당하는 IB 에러 코드
DROP_ERRORS   = frozenset({101, 200, 354})
# 101 = Max number of tickers has been reached (한도 도달)
LIMIT_ERRORS  = frozenset({101})


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":      # 윈도우는 os.kill(pid, 0) 의미가 다름 → 하트비트만 신뢰
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return True
    return True


class LineRegistry:
    """한 프로세스의 시세 라인 점유 목록 + 다른 프로세스 합산."""

    def __init__(self,
                 app: str,
                 limit: int = DEFAULT_LIMIT,
                 directory: Optional[str] = None,
                 heartbeat_s: float = 2.0,
                 stale_s: float = 10.0,
                 on_change: Optional[Callable[[dict], None]] = None,
                 start: bool = True) -> None:
        self.app         = app
        self.limit       = int(limit)
        self.dir         = directory or os.environ.get("HTS_LINE_DIR") or DEFAULT_DIR
        self.heartbeat_s = heartbeat_s
        self.stale_s     = stale_s
        self.on_change   = on_change

        self._lock       = threading.RLock()
        self._mine: Dict[Hashable, str] = {}  # 키: reqId(int) 또는 별도 클라이언트용 문자열 키
        self._limit_hit  = False
        self._dirty      = True
        self._last_write = 0.0
        self._last_pub   = None            # 마지막 발행 스냅샷(변화 없으면 재발행 안 함)
        self._pid        = os.getpid()
        self._path       = os.path.join(self.dir, f"{self.app}_{self._pid}.json")
        self._stop       = threading.Event()
        self._thread: Optional[threading.Thread] = None
        try:
            os.makedirs(self.dir, exist_ok=True)
        except Exception:
            pass
        if start:
            self.start()

    # ── 수명 주기 ────────────────────────────────────────────
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name=f"LineRegistry-{self.app}", daemon=True)
        self._thread.start()
        atexit.register(self.close)

    def close(self) -> None:
        self._stop.set()
        try:
            os.remove(self._path)
        except Exception:
            pass

    def _loop(self) -> None:
        while not self._stop.wait(0.25):
            try:
                self.flush()
            except Exception:
                pass

    # ── 등록/해제 ────────────────────────────────────────────
    def try_reserve(self, req_id: int, tag: str = "") -> bool:
        """한도 검사 + 등록을 한 번에(원자적). 한도를 넘으면 False — 이때 reqMktData 를 호출하지 말 것."""
        with self._lock:
            if req_id in self._mine:
                return True
            if len(self._mine) + self._others_count_locked() >= self.limit:
                self._limit_hit = True
                self._dirty = True
                return False
            self._mine[req_id] = tag
            self._dirty = True
            return True

    def add(self, req_id: int, tag: str = "") -> None:
        """한도 검사 없이 등록(이미 구독이 나간 경로용)."""
        with self._lock:
            if req_id not in self._mine:
                self._mine[req_id] = tag
                self._dirty = True

    def release(self, req_id: int) -> bool:
        with self._lock:
            if self._mine.pop(req_id, None) is None:
                return False
            if len(self._mine) + self._others_count_locked() < self.limit:
                self._limit_hit = False
            self._dirty = True
            return True

    def release_many(self, req_ids) -> int:
        n = 0
        for r in list(req_ids):
            if self.release(r):
                n += 1
        return n

    def clear(self) -> None:
        """연결 끊김/재연결 시 전부 비움."""
        with self._lock:
            if self._mine:
                self._mine.clear()
                self._dirty = True
            self._limit_hit = False

    def on_ib_error(self, req_id: int, code: int) -> bool:
        """IB 에러 수신 시 호출. 라인을 점유하지 못한 요청이면 목록에서 제거. 제거했으면 True."""
        dropped = False
        with self._lock:
            if code in LIMIT_ERRORS:
                self._limit_hit = True
                self._dirty = True
            if code in DROP_ERRORS and req_id in self._mine:
                del self._mine[req_id]
                self._dirty = True
                dropped = True
        return dropped

    # ── 조회 ─────────────────────────────────────────────────
    def local_count(self) -> int:
        with self._lock:
            return len(self._mine)

    def others_count(self) -> int:
        return self.others()[0]

    def total(self) -> int:
        with self._lock:
            return len(self._mine) + self._others_count_locked()

    def available(self) -> int:
        return max(0, self.limit - self.total())

    @property
    def limit_hit(self) -> bool:
        return self._limit_hit

    def others(self):
        """(다른 앱 라인 합계, {앱: 수}) — 하트비트 신선 + PID 생존 파일만."""
        total, detail = 0, {}
        now = time.time()
        try:
            files = glob.glob(os.path.join(self.dir, "*.json"))
        except Exception:
            files = []
        for f in files:
            if os.path.abspath(f) == os.path.abspath(self._path):
                continue
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    d = json.load(fp)
                if now - float(d.get("ts", 0)) > self.stale_s:
                    continue
                if not _pid_alive(int(d.get("pid", 0))):
                    continue
                n = int(d.get("count", 0))
            except Exception:
                continue
            total += n
            detail[str(d.get("app", "?"))] = detail.get(str(d.get("app", "?")), 0) + n
        return total, detail

    def _others_count_locked(self) -> int:
        # 파일 읽기는 가볍지만 try_reserve 가 연타될 수 있어 0.5초 캐시
        now = time.time()
        c = getattr(self, "_oc_cache", None)
        if c and now - c[0] < 0.5:
            return c[1]
        n = self.others()[0]
        self._oc_cache = (now, n)
        return n

    def snapshot(self) -> dict:
        with self._lock:
            local = len(self._mine)
            tags: Dict[str, int] = {}
            for t in self._mine.values():
                tags[t or "?"] = tags.get(t or "?", 0) + 1
        others, detail = self.others()
        total = local + others
        return {
            "app":       self.app,
            "local":     local,
            "others":    others,
            "others_detail": detail,
            "count":     total,           # 기존 상태바 호환: count = 합계
            "total":     total,
            "max":       self.limit,
            "ratio":     (total / self.limit) if self.limit > 0 else 0.0,
            "limit_hit": self._limit_hit,
            "by_tag":    tags,
        }

    # ── 파일 기록 + 변경 알림 ────────────────────────────────
    def flush(self, force: bool = False) -> None:
        now = time.time()
        with self._lock:
            need_write = force or self._dirty or (now - self._last_write >= self.heartbeat_s)
            local = len(self._mine)
            tags: Dict[str, int] = {}
            for t in self._mine.values():
                tags[t or "?"] = tags.get(t or "?", 0) + 1
            self._dirty = False
        if need_write:
            self._write(local, tags, now)
        if self.on_change is not None:
            snap = self.snapshot()
            key = (snap["local"], snap["others"], snap["limit_hit"], snap["max"])
            if force or key != self._last_pub:
                self._last_pub = key
                try:
                    self.on_change(snap)
                except Exception:
                    pass

    def _write(self, local: int, tags: dict, now: float) -> None:
        try:
            os.makedirs(self.dir, exist_ok=True)
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fp:
                json.dump({"app": self.app, "pid": self._pid, "count": local,
                           "ts": now, "by_tag": tags}, fp)
            os.replace(tmp, self._path)
            self._last_write = now
        except Exception:
            pass


# ── 프로세스 단일 인스턴스 ─────────────────────────────────────
_REG: Optional[LineRegistry] = None
_REG_LOCK = threading.Lock()


def get_line_registry(app: Optional[str] = None, **kw) -> Optional[LineRegistry]:
    """프로세스 공용 레지스트리. app 을 주면 최초 1회 생성, 없으면 이미 만들어진 것만 반환(없으면 None)."""
    global _REG
    with _REG_LOCK:
        if _REG is None and app:
            _REG = LineRegistry(app, **kw)
        return _REG
