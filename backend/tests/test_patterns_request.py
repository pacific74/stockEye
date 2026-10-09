"""검색 종목 패턴 요청 처리: 대기 → 처리 → stock_details 갱신 · 상태 기록"""
import numpy as np
import pandas as pd

from stockeye.cloud.patterns import process_pattern_requests


class FakeSB:
    def __init__(self, reqs, detail_codes):
        self.reqs = reqs
        self.details = {c: {} for c in detail_codes}
        self.updates = []

    def select(self, table, params=None):
        return [r for r in self.reqs if r["status"] == "queued"] if table == "pattern_requests" else []

    def update(self, table, filters, patch, returning=False):
        self.updates.append((table, filters, patch))
        if table == "stock_details":
            code = filters["code"][3:]
            if code in self.details:
                self.details[code].update(patch)
                return [{"code": code}]
            return []
        if table == "pattern_requests":
            f = filters["id"]
            ids = [int(x) for x in f[4:-1].split(",")] if f.startswith("in.") else [int(f[3:])]
            for r in self.reqs:
                if r["id"] in ids:
                    r.update(patch)
        return []


class FakePit:
    def __init__(self):
        rng = np.random.default_rng(1)
        d = pd.bdate_range("2023-01-02", periods=400)
        rows = []
        for k in range(40):
            code = f"{k:05d}0"
            r = rng.normal(0, 0.02, len(d))
            c = 10000 * np.exp(np.cumsum(r))
            rows.append(pd.DataFrame({"date": d, "code": code, "open": c, "high": c * 1.01, "low": c * 0.99, "close": c,
                                      "volume": 1e5, "value": 5e9 * (1 + rng.random(len(d))), "chg_pct": r * 100}))
        self.ohlcv = pd.concat(rows, ignore_index=True)
        self.listing = pd.DataFrame({"code": [f"{k:05d}0" for k in range(40)], "name": [f"종목{k}" for k in range(40)]})


def test_process_requests():
    reqs = [{"id": 1, "code": "000010", "status": "queued"}, {"id": 2, "code": "000020", "status": "queued"},
            {"id": 3, "code": "999990", "status": "queued"}]
    sb = FakeSB(reqs, ["000010", "000020"])
    assert process_pattern_requests(sb, FakePit()) == 3
    sp = sb.details["000010"]["similar_patterns"]
    assert sp["matches"] and {"sim_price", "sim_ma", "sim_volume"} <= set(sp["matches"][0])
    assert sp["basis"].startswith("가격 모양")
    st = {r["id"]: r["status"] for r in reqs}
    assert st[1] == "done" and st[2] == "done" and st[3] == "failed"
    assert process_pattern_requests(sb, FakePit()) == 0          # 대기 없음
