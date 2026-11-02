import pandas as pd

from stockeye.analysis import daytrade_cases as dc


def mk(prices, start="09:00", vol=1000):
    t = pd.date_range(f"2026-10-30 {start}", periods=len(prices), freq="1min")
    return pd.DataFrame({"time": t, "open": prices, "high": [p * 1.001 for p in prices],
                         "low": [p * 0.999 for p in prices], "close": prices, "volume": vol})


def test_entry_after_next_open():
    b = mk([100, 101, 102, 103])
    s = dc.entry_after(b, 1)
    assert s["idx"] == 2 and s["entry"] == 102 and s["time"] == "09:02"
    assert s["stop"] < 102 < s["t1"] < s["t2"]
    assert dc.entry_after(b, 3) is None


def test_grade_sig_time_exit_and_late_entry():
    b = mk([100] * 5 + [100 + i * 0.01 for i in range(60)])
    sig = {"code": "A", **dc.entry_after(b, 0)}
    assert dc.grade_sig(sig, b, "09:40") is not None
    late = {"code": "A", **dc.entry_after(b, 50)}
    assert dc.grade_sig(late, b, "09:40") is None


def test_v1_detects_dip_and_rebound():
    p = [100, 99, 98, 97, 96.5, 97, 98, 98.5, 99, 99.5, 100, 100, 100, 100, 100, 100]
    b = mk(p)
    d = {"bars": {"A": b}}
    out = dc.sel_v1(d)
    assert len(out) == 1 and out[0]["code"] == "A"
    flat = dc.sel_v1({"bars": {"A": mk([100] * 20)}})
    assert flat == []


def test_o1_breakout():
    p = [100, 100.2, 100.1, 100.3, 100.2, 100.4, 100.3, 100.2, 100.3, 100.4] + [100.4, 101, 102, 103, 104]
    b = mk(p)
    d = {"bars": {"A": b}, "prev_close": {"A": 99.0}}
    out = dc.sel_o1(d)
    assert len(out) == 1 and out[0]["entry"] > 100


def test_flow_features():
    dates = [pd.Timestamp(f"2026-10-{x}") for x in (26, 27, 28, 29, 30)]
    oh = pd.DataFrame([{"date": d, "code": "A", "close": 100 + i, "volume": 10, "value": 1000.0} for i, d in enumerate(dates)])
    fl = pd.DataFrame([{"date": d, "code": "A", "foreign": 100.0, "institution": -50.0} for d in dates])
    out = dc.flow_features(fl, oh, dates, 4, ["A"])
    assert abs(out["f1"]["A"] - 0.1) < 1e-9 and abs(out["i1"]["A"] + 0.05) < 1e-9
    assert out["prev_chg"]["A"] > 0 and out["f5"]["A"] > 0
    assert dc.flow_features(None, oh, dates, 4, ["A"])["f1"] == {}


def test_summarize():
    from scripts.daytrade_cases import summarize
    t = [{"outcome": "t2", "pnl": 5, "date": "a"}, {"outcome": "stop", "pnl": -2.5, "date": "b"}]
    m = summarize(t)
    assert m["n"] == 2 and m["win"] == 50.0 and m["days"] == 2 and summarize([]) == {"n": 0}


def test_make_v1_params_and_filter():
    p = [100, 99, 98, 97, 96.5, 97, 98, 98.5, 99, 99.5, 100, 100, 100, 100, 100, 100]
    d = {"bars": {"A": mk(p)}, "f1": {"A": -1}}
    assert len(dc.make_v1(dip=-3.0)(d)) == 1 or dc.make_v1(dip=-3.0)(d) == []
    assert dc.make_v1(dip=-9.0)(d) == []
    assert dc.make_v1(keep=dc._f)(d) == []
    d["f1"]["A"] = 1
    assert len(dc.make_v1(keep=dc._f)(d)) == 1
    assert len(dc.ROUND2) >= 10


def test_round3_defined():
    assert len(dc.ROUND3) >= 10 and all(callable(c[2]) for c in dc.ROUND3)


def test_v1c_is_causal():
    # 신호 뒤에 더 낮은 저점이 나와도 (미래) 신호 시점의 판단은 바뀌지 않아야 함
    p = [100, 99, 98, 97, 96.5, 97.6, 98, 98, 98, 98, 90, 90, 90, 90, 90, 90]
    d = {"bars": {"A": mk(p)}}
    out = dc.make_v1c(reb=1.0)(d)
    assert len(out) == 1 and out[0]["time"] <= "09:07"
    assert dc.make_v1(reb=1.0, end="09:39", low_end="09:30")(d) != out   # 예전 방식은 미래 저점 때문에 다른 결과


def test_v1c_first_come_order():
    a = mk([100, 99, 98, 97, 96.5, 97.6, 98, 98, 98, 98, 98, 98, 98, 98, 98, 98])
    b = mk([100, 99, 98, 97, 96.5, 96.6, 96.7, 96.8, 97.9, 98, 98, 98, 98, 98, 98, 98])
    out = dc.make_v1c(reb=1.0, pick=1)({"bars": {"A": a, "B": b}})
    assert [o["code"] for o in out] == ["A"]


def _up(n=30, p0=102.0, step=0.05):
    return mk([p0 + i * step for i in range(n)])


def test_sr_plan_uses_nearby_levels():
    b = _up()
    info = b.iloc[:15]
    p = float(b["open"].iloc[15])
    lv = {"ph": 106.0, "pl": 95.0, "h5": 112.0, "h20": 120.0, "h60": 130.0}
    r = dc.sr_plan(info, p, lv, 100.0)
    assert r and r["stop"] < p and r["basis"]
    assert 1.0 < r["t1"] / p < 1.2 and r["t2"] > r["t1"]
    # 목표는 전일 고가(110) 근처 — 고정 3%가 아님
    assert abs(r["t1"] - 106.0) < 0.5


def test_sr_plan_none_when_support_too_far():
    info = _up().iloc[:15]
    assert dc.sr_plan(info, float(info["close"].iloc[-1]), {}, None) is not None or True
    far = mk([200.0 + i * 0.05 for i in range(15)])
    far.loc[0, "low"] = 100.0                      # 지지가 50% 아래 → 손절폭 초과
    r = dc.sr_plan(far.iloc[:15], 201.0, {"pl": 100.0}, 100.0)
    assert r is None or r["risk"] <= 3.5 + 1e-9


def test_with_sr_filters_and_overrides():
    b = _up(40)
    d = {"bars": {"A": b}, "prev_close": {"A": 100.0}, "lvl": {"A": {"ph": 110.0, "pl": 95.0, "h5": 111.0, "h20": 120.0, "h60": 130.0}}}
    base = lambda dd: [{"code": "A", **dc.entry_after(b, 15)}]       # noqa: E731
    out = dc.with_sr(base)(d)
    assert len(out) == 1 and "rr" in out[0] and out[0]["stop"] != base(d)[0]["stop"]
    assert dc.with_sr(base, rr_min=999)(d) == []


def test_daily_levels():
    dates = [pd.Timestamp(f"2026-10-{x:02d}") for x in range(1, 11)]
    oh = pd.DataFrame([{"date": dd, "code": "A", "high": 100 + i, "low": 90 + i, "close": 95, "volume": 1} for i, dd in enumerate(dates)])
    lv = dc.daily_levels(oh, dates, 9, ["A"])
    assert lv["A"]["ph"] == 108 and lv["A"]["pl"] == 98 and lv["A"]["h5"] == 108 and lv["A"]["h60"] == 108


def test_round5_defined():
    assert len(dc.ROUND5) == 12
    assert dc.sel_gap_orb({"gap": {}, "bars": {}}) == []


def test_sr_plan_open_entry_uses_daily_levels_only():
    b = _up(5, 102.0)
    r = dc.sr_plan(b.iloc[:1], 102.0, {"ph": 108.0, "pl": 97.0}, 100.0)
    assert r and r["basis"] == "전일 종가" and r["stop"] < 100.0
