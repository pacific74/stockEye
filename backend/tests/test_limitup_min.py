import pandas as pd

from stockeye.analysis import limitup_min as lm


def mk(prices, hi_add=0.0, lo_sub=0.0):
    t = pd.date_range("2026-10-30 09:00", periods=len(prices), freq="1min")
    return pd.DataFrame({"time": t, "open": prices, "high": [p * (1 + hi_add) for p in prices],
                         "low": [p * (1 - lo_sub) for p in prices], "close": prices, "volume": 1000})


def test_entry_open_skips_limit_gap():
    b = mk([130.0] * 20)
    assert lm.entry_open(b, 100.0) is None            # 시가 +30% = 이미 상한가
    assert lm.entry_open(mk([105.0] * 20), 100.0)["px"] == 105.0


def test_confirm_fail_exits_early():
    b = mk([100.0] * 30)                                # 안 오름
    e = lm.entry_open(b, 95.0)
    r = lm.run_exit(b, e, confirm_min=5, confirm_pct=1.0)
    assert r["why"] == "확인실패" and r["time"] == "09:04"
    assert abs(r["pnl"] + lm.COST) < 1e-9


def test_confirm_ok_holds_to_time_exit():
    p = [100.0] * 3 + [102.0] * 30
    b = mk(p)
    e = lm.entry_open(b, 95.0)
    r = lm.run_exit(b, e, confirm_min=5, confirm_pct=1.0, until="09:20")
    assert r["why"] == "시간" and r["pnl"] > 1.5


def test_stop_first_in_same_bar():
    b = mk([100.0] * 10, hi_add=0.10, lo_sub=0.05)    # 한 봉에 +10% / −5% 둘 다
    e = lm.entry_open(b, 95.0)
    r = lm.run_exit(b, e, target=5.0)
    assert r["why"] == "손절"


def test_breakeven_after_confirm():
    p = [100.0, 101.5, 101.5, 99.5, 99.5, 99.5] + [99.5] * 10
    b = mk(p)
    e = lm.entry_open(b, 95.0)
    r = lm.run_exit(b, e, confirm_min=3, confirm_pct=1.0, be=True)
    assert r["why"] == "본전"


def test_orb_entry():
    p = [100, 100.5, 100.2, 100.3, 100.8, 101.5, 102, 102, 102, 102, 102, 102]
    b = mk([float(x) for x in p] + [102.0] * 10)
    e = lm.entry_orb(b, 99.0, n=3)
    assert e and e["kind"] == "돌파" and e["idx"] >= 4
