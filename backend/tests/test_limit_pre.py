import pandas as pd

from stockeye.engine import limit_pre as lp


def _bars(n=30, base=1000.0, last_mult=4.0):
    t = pd.date_range("2026-10-16 09:00", periods=n, freq="min")
    close = [base + i for i in range(n)]
    vol = [1000.0] * (n - 5) + [1000.0 * last_mult] * 5
    return pd.DataFrame({"time": t, "open": close, "high": [c + 1 for c in close], "low": [c - 1 for c in close],
                         "close": close, "volume": vol})


def _daily(hit=False):
    c = [1000.0] * 40
    if hit:
        c[30] = 1300.0
        c[31:] = [1300.0] * 9
    return pd.DataFrame({"close": c})


def test_evaluate_pre():
    now = pd.Timestamp("2026-10-16 09:40")
    q = {"price": 1150.0, "high": 1152.0, "change_pct": 15.0, "value": 40e8, "prev_close": 1000.0}
    book = {"total_bid": 30000, "total_ask": 10000}
    r = lp.evaluate(_daily(hit=True), q, _bars(), book, {"now": now})
    assert r["status"] == "상한가 예비" and r["score"] >= 60
    assert r["parts"]["accel25"] == 25 and r["parts"]["hist10"] == 10 and r["parts"]["book15"] == 15
    # 고가에서 많이 밀림 → 대상 아님
    assert lp.evaluate(_daily(), {**q, "high": 1200.0}, _bars(), book, {"now": now})["status"] == "대상 아님"
    # +20% 이상은 상한가포착 단계 · 시간 밖 · 거래대금 부족
    assert lp.evaluate(_daily(), {**q, "change_pct": 21}, _bars(), book, {"now": now})["status"] == "대상 아님"
    assert lp.evaluate(_daily(), q, _bars(), book, {"now": pd.Timestamp("2026-10-16 14:45")})["status"] == "대상 아님"
    assert lp.evaluate(_daily(), {**q, "value": 20e8}, _bars(), book, {"now": now})["status"] == "대상 아님"
    assert lp.evaluate(_daily(), q, _bars(), book, {"now": now, "danger": "관리종목"})["status"] == "제외"


def test_grade_and_stats():
    g = lp.grade({"price": 1150}, {"high": 1300, "close": 1300}, 1300)
    assert g == {"reached": True, "closed": True, "high_ret": 13.04, "close_ret": 13.04}
    g2 = lp.grade({"price": 1150}, {"high": 1300, "close": 1200}, 1300)
    assert g2["reached"] and not g2["closed"]
    st = lp.stats([{"score": 85, **g}, {"score": 65, **g2}])
    assert st["all"] == {"n": 2, "reached": 100.0, "closed": 50.0, "close_ret": round((13.04 + 4.35) / 2, 2)}
    assert st["bands"][0]["n"] == 1 and st["bands"][2]["closed"] == 0.0


def test_grade_day():
    from stockeye.analysis.limit_pre_eval import grade_day
    rows = [{"date": "2026-10-16", "code": "A", "price": 1150, "prev_close": 1000, "score": 70},
            {"date": "2026-10-16", "code": "B", "price": 100, "prev_close": 90, "score": 61}]
    out = grade_day(rows, {"A": {"high": 1300, "close": 1250}})
    assert len(out) == 1 and out[0]["reached"] and not out[0]["closed"]
