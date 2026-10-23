"""LineRegistry 테스트 — 단일 프로세스 + 실제 2프로세스 합산.  python3 -m pytest 또는 직접 실행"""
import os, sys, time, json, tempfile, subprocess, threading
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.line_registry import LineRegistry


def mk(app, d, **kw):
    return LineRegistry(app, directory=d, start=False, **kw)


def test_reserve_and_limit():
    d = tempfile.mkdtemp()
    r = mk("A", d, limit=5)
    assert all(r.try_reserve(i, "chain") for i in range(5))
    assert not r.try_reserve(99, "chain") and r.limit_hit
    assert r.try_reserve(0)                      # 이미 등록 → True(중복 카운트 없음)
    assert r.local_count() == 5
    r.release(0)
    assert r.local_count() == 4 and not r.limit_hit
    assert r.try_reserve(99)


def test_race_never_exceeds_limit():
    d = tempfile.mkdtemp()
    r = mk("A", d, limit=95)
    ok = []
    def w(base):
        for i in range(60):
            if r.try_reserve(base + i, "chain"):
                ok.append(1)
    ts = [threading.Thread(target=w, args=(k * 1000,)) for k in range(4)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert r.local_count() == 95 and len(ok) == 95   # 240 시도해도 95 초과 불가


def test_error_codes():
    d = tempfile.mkdtemp()
    r = mk("A", d, limit=10)
    r.try_reserve(1); r.try_reserve(2); r.try_reserve(3)
    assert r.on_ib_error(1, 200) and r.local_count() == 2     # 없는 종목 → 라인 아님
    assert not r.on_ib_error(77, 200)                          # 모르는 id 는 무시
    assert not r.on_ib_error(2, 2104)                          # 정보성 메시지는 제거 안 함
    r.on_ib_error(2, 101)
    assert r.limit_hit and r.local_count() == 1


def test_two_apps_sum_and_stale():
    d = tempfile.mkdtemp()
    a = mk("tradier", d, limit=100, stale_s=1.0)
    b = mk("ibkr_stock", d, limit=95, stale_s=1.0)
    for i in range(60): a.try_reserve(i, "chain")
    a.flush(force=True)
    for i in range(30): assert b.try_reserve(i, "scan")
    b.flush(force=True)
    assert b.others_count() == 60 and a.others()[0] == 30
    sb = b.snapshot()
    assert sb["total"] == 90 and sb["local"] == 30 and sb["others"] == 60
    # 합산 기준으로 한도 적용: b 가 11개 더 요청 → 5개만 성공 (95-90)
    time.sleep(0.6)                      # others 캐시 만료
    got = sum(1 for i in range(100, 111) if b.try_reserve(i, "scan"))
    assert got == 5, got
    # 하트비트 끊기면(= a 가 죽은 것으로 간주) 합산에서 빠짐
    time.sleep(1.2)
    assert b.others_count() == 0


def test_two_real_processes():
    d = tempfile.mkdtemp()
    code = ("import sys,time; sys.path.insert(0,%r);"
            "from core.line_registry import LineRegistry as L;"
            "r=L('child',directory=%r);"
            "[r.try_reserve(i,'x') for i in range(40)];"
            "r.flush(force=True);print('ready',flush=True);time.sleep(3)") % (
            os.path.join(os.path.dirname(__file__), ".."), d)
    p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    try:
        assert p.stdout.readline().strip() == "ready"
        me = mk("parent", d)
        for i in range(10): me.try_reserve(i)
        assert me.others_count() == 40 and me.snapshot()["total"] == 50
    finally:
        p.kill(); p.wait()
    time.sleep(0.1)
    assert me.others_count() == 0        # 프로세스 종료(PID 없음) → 즉시 제외, 하트비트 만료 대기 불필요


def test_on_change_publishes_only_on_change():
    d = tempfile.mkdtemp()
    got = []
    r = LineRegistry("A", directory=d, on_change=got.append, start=False)
    r.try_reserve(1); r.flush()
    r.flush(); r.flush()
    assert len(got) == 1 and got[0]["local"] == 1 and got[0]["count"] == 1
    r.try_reserve(2); r.flush()
    assert len(got) == 2


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("PASS", n)
