import pandas as pd

from stockeye.analysis import minute_archive as ma


def test_pick_combines_value_movers_and_carry():
    rows = [{"code": f"{i:06d}", "chg_pct": 0.0, "value": 1e12 - i * 1e9} for i in range(200)]
    rows += [{"code": "900001", "chg_pct": 12.0, "value": 5e9}, {"code": "900002", "chg_pct": -9.0, "value": 4e9},
             {"code": "900003", "chg_pct": 20.0, "value": 1e9}]           # 거래대금 작은 급등은 제외
    s = pd.DataFrame(rows)
    out = ma.pick(s, ["777777"])
    assert len(out) == len(set(out))
    assert "000000" in out and "000149" in out and "000150" not in out
    assert "900001" in out and "900002" in out and "900003" not in out and "777777" in out


def test_hot_and_empty():
    s = pd.DataFrame({"code": ["a", "b"], "chg_pct": [29.9, 3.0], "value": [1, 1]})
    assert ma.hot(s) == ["a"]
    assert ma.pick(pd.DataFrame(), ["x"]) == ["x"] and ma.hot(pd.DataFrame()) == []


def test_market_window_and_missing_days():
    mon_am = pd.Timestamp("2026-11-02 09:30")
    assert ma.in_market_window(mon_am) and not ma.in_market_window(pd.Timestamp("2026-11-02 15:45"))
    assert not ma.in_market_window(pd.Timestamp("2026-11-02 08:20")) and not ma.in_market_window(pd.Timestamp("2026-11-01 10:00"))
    days = pd.bdate_range("2026-10-26", "2026-10-30")
    miss = ma.missing_days(list(days), {"20261027", "20261029"}, lookback=4)
    assert [d.strftime("%Y%m%d") for d in miss] == ["20261028", "20261030"]
