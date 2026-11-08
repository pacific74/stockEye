import json

import pandas as pd

from stockeye.analysis import ledger
from stockeye.engine import daytrade as dt, params as pm
from scripts import weekly_optimize as wo


class FakeSB:
    def __init__(self):
        self.f = {}

    def upload(self, p, b, ct=None):
        self.f[p] = b

    def download(self, p):
        return self.f.get(p)


def test_params_apply_and_bounds():
    old = dt.MIN_ADR
    assert pm.apply(dt, {"min_adr": 0.99, "nope": 1}) == {}
    assert dt.MIN_ADR == old
    with pm.Overrides(dt, {"min_adr": 0.06}):
        assert dt.MIN_ADR == 0.06
    assert dt.MIN_ADR == old


def test_params_save_history():
    sb = FakeSB()
    o = pm.save(sb, {"entry_score": 83}, "t", "2026-11-09 10:00")
    o = pm.save(sb, {"vwap_chase": 0.04, "bad": 1}, "t2", "2026-11-10 10:00")
    assert o["version"] == 2 and o["params"] == {"entry_score": 83.0, "vwap_chase": 0.04} and len(o["history"]) == 2


def _oh(n=40):
    rows = []
    for i in range(n):
        d = pd.Timestamp("2026-09-01") + pd.Timedelta(days=i)
        for c, vol, g in (("A", 1e6, 1.0), ("B", 5e6, 1.0), ("C", 100, 1.0)):
            p = 1000 * (1 + (0.1 if (i == n - 1 and c == "A") else 0))
            rows.append({"date": d, "code": c, "open": p, "high": p * 1.06, "low": p * 0.97, "close": p * g, "volume": vol})
    return pd.DataFrame(rows)


def test_ledger_universe_min_value_and_forward():
    oh = _oh()
    day = oh["date"].max()
    rows = ledger.build(oh, day, {"A": "에이"})
    codes = {r["code"] for r in rows}
    assert "C" not in codes and {"A", "B"} <= codes          # 거래대금 10억 미만 제외
    a = [r for r in rows if r["code"] == "A"][0]
    assert a["chg"] == 10.0 and "상승상위" in a["src"] and a["name"] == "에이"
    sb = FakeSB()
    assert ledger.run(sb, oh, day.strftime("%Y-%m-%d"))["rows"] == len(rows)
    assert json.loads(sb.f[f"ledger/{day:%Y-%m-%d}.json"])["rows"]


def test_judge_requires_both_periods():
    mk = lambda d, p: {"date": d, "pnl": p}
    base = [mk("2026-10-01", 0.0)] * 30 + [mk("2026-10-20", 0.0)] * 15
    good = [mk("2026-10-01", 0.5)] * 30 + [mk("2026-10-20", 0.2)] * 15
    bad_hold = [mk("2026-10-01", 0.5)] * 30 + [mk("2026-10-20", -0.5)] * 15
    assert wo.judge(base, good, "2026-10-10")
    assert wo.judge(base, bad_hold, "2026-10-10") is None
    assert wo.judge(base, good[:10], "2026-10-10") is None   # 거래 수 급감
