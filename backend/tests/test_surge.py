import json
import numpy as np
import pandas as pd

from stockeye.engine import surge as sg


def _pit(n_days=420, n_codes=60, seed=1):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2025-01-01", periods=n_days)
    rows, fl = [], []
    for i in range(n_codes):
        code = f"{100000 + i * 10:06d}"
        p = 5000.0
        for d in dates:
            chg = rng.normal(0, 2.5)
            if rng.random() < 0.004:
                chg = 29.9
            o = p * (1 + rng.normal(0, 0.01))
            c = p * (1 + chg / 100)
            h, l = max(o, c) * 1.01, min(o, c) * 0.99
            if chg > 29:
                h = c
            rows.append((code, d, o, h, l, c, 1e6, c * 1e6 * (1 + abs(chg) / 5), chg))
            fl.append((code, d, rng.normal(0, 1e7), rng.normal(0, 1e7), rng.normal(0, 1e7)))
            p = c
    oh = pd.DataFrame(rows, columns=["code", "date", "open", "high", "low", "close", "volume", "value", "chg_pct"])
    oh["value"] = oh["value"].clip(lower=2e9)
    flows = pd.DataFrame(fl, columns=["code", "date", "foreign", "institution", "individual"])
    codes = oh.code.unique()
    ls = pd.DataFrame({"code": codes, "name": [f"종목{i}" for i in range(len(codes))]})
    sec = pd.DataFrame({"code": codes, "sector": ["A", "B"] * (len(codes) // 2), "market": ["KOSDAQ"] * len(codes),
                        "marcap": [3e11] * len(codes)})
    fu = oh[["code", "date"]].assign(per=10.0, pbr=1.0)
    ix = pd.concat([pd.DataFrame({"date": dates, "code": m, "close": 1000 + np.arange(len(dates)) * 1.0}) for m in ("KOSPI", "KOSDAQ")])

    class P:
        pass
    p = P()
    p.ohlcv, p.flows, p.fund, p.index, p.listing, p.sectors = oh, flows, fu, ix, ls, sec
    return p


class FakeSb:
    def __init__(self):
        self.files, self.status = {}, {}

    def upload(self, path, data, ctype="application/json"):
        self.files[path] = data

    def download(self, path):
        return self.files.get(path)

    def upsert(self, table, rows, key):
        for r in rows:
            self.status[r["key"]] = r["payload"]


def test_prepare_fit_pick():
    pit = _pit()
    p = sg.prepare(pit, days=500)
    last = p.date.max()
    assert p[p.date == last].y.isna().all()                     # 마지막 날은 정답 없음
    m, info = sg.fit(p)
    assert info["pos"] >= 50
    r = sg.pick(p, m, last, top=5)
    assert len(r["items"]) == 5 and r["items"][0]["score"] >= r["items"][-1]["score"]
    assert all(i["reasons"] for i in r["items"])


def test_grade_and_stats():
    items = [{"code": "A", "name": "a", "rank": 1, "score": 5, "close": 1000.0}, {"code": "B", "name": "b", "rank": 2, "score": 4, "close": 1000.0}]
    bars = {"A": {"open": 1100, "high": 1300, "low": 1090, "close": 1300}, "B": {"open": 1000, "high": 1050, "low": 950, "close": 960}}
    g = sg.grade(items, bars)
    assert g[0]["closed"] and g[0]["reached"] and g[0]["h20"]
    assert not g[1]["reached"] and g[1]["close"] == -4.0
    for r in g:
        r["date"] = "2026-11-02"
    s = sg.stats(g)
    assert s["all"]["n"] == 2 and s["all"]["closed"] == 50.0 and s["top5"]["n"] == 2


def test_reasons_fallback():
    assert sg.reasons({"vr1": 1.0}) == ["모델 점수 상위"]
    assert "거래대금 3.0배" in sg.reasons({"vr1": 3.0})


def test_run_twice_grades_previous():
    from stockeye.analysis import surge_eval as ev
    pit = _pit()
    sb = FakeSb()
    # 하루 전 기준으로 먼저 목록 만들기 (마지막 날을 잘라낸 데이터)
    last = pit.ohlcv.date.max()
    full = pit.ohlcv
    pit.ohlcv = full[full.date < last]
    pit.flows = pit.flows[pit.flows.date < last]
    pit.fund = pit.fund[pit.fund.date < last]
    r1 = ev.run(sb, pit, "2026-01-01")
    assert r1["graded"] == 0
    pit.ohlcv, pit.flows = full, pit.flows
    pit2 = _pit()
    r2 = ev.run(sb, pit2, "2026-01-02")
    assert r2["graded"] >= 1
    s = sb.status["surge"]
    assert s["prev"]["n"] == 20 and len(s["items"]) == 20
    assert "surge_stats" in sb.status
    assert json.loads(sb.files["surge/results.json"])["days"]
