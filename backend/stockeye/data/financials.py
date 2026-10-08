"""재무 지표 (V2 재무 15점용) — DART 주요계정(financials.parquet) → 보고서별 지표 → 날짜 기준 조회.

보고서 1건(종목, 연도, 분기)마다:
  수익성  op_pos(영업이익 흑자), op_margin(영업이익률), roe(연환산 ROE), op_improve(작년 같은 기간 대비 영업이익 개선)
  성장성  rev_yoy, op_yoy, ni_yoy  (작년 같은 기간 누적 대비)
  건전성  debt_ratio(부채/자본), current_ratio(유동자산/유동부채), impaired(자본잠식: 자본총계 < 자본금)
조회: at(as_of) → 각 종목의 'as_of 이전에 접수된' 가장 최근 보고서 지표 (미래참조 없음).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

Q = {"Q1": 1, "H1": 2, "Q3": 3, "FY": 4}


def _yoy(cur, prev):
    cur, prev = np.asarray(cur, float), np.asarray(prev, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(np.abs(prev) > 0, (cur - prev) / np.abs(prev), np.nan)
    return out


def build_metrics(fin: pd.DataFrame) -> pd.DataFrame:
    if fin is None or fin.empty:
        return pd.DataFrame()
    f = fin.copy()
    f["q"] = f["reprt"].map(Q)
    f = f.sort_values(["code", "year", "q", "date"]).drop_duplicates(["code", "year", "reprt"], keep="last")
    prev = f[["code", "year", "reprt", "revenue", "op_income", "net_income"]].copy()
    prev["year"] = prev["year"] + 1
    f = f.merge(prev, on=["code", "year", "reprt"], how="left", suffixes=("", "_py"))
    num = lambda c: pd.to_numeric(f.get(c), errors="coerce")
    rev, op, ni = num("revenue"), num("op_income"), num("net_income")
    eq, liab, cap = num("equity"), num("liabilities"), num("capital")
    ca, cl = num("cur_assets"), num("cur_liab")
    out = pd.DataFrame({"code": f["code"], "date": pd.to_datetime(f["date"]), "year": f["year"], "reprt": f["reprt"]})
    out["op_pos"] = (op > 0).where(op.notna())
    with np.errstate(divide="ignore", invalid="ignore"):
        out["op_margin"] = np.where(rev > 0, op / rev, np.nan)
        out["roe"] = np.where(eq > 0, ni * (4 / f["q"]) / eq, np.nan)
        out["debt_ratio"] = np.where(eq > 0, liab / eq, np.nan)
        out["current_ratio"] = np.where(cl > 0, ca / cl, np.nan)
    out["impaired"] = ((eq < cap) | (eq <= 0)).where(eq.notna() & cap.notna())
    out["rev_yoy"] = _yoy(rev, num("revenue_py"))
    out["op_yoy"] = _yoy(op, num("op_income_py"))
    out["ni_yoy"] = _yoy(ni, num("net_income_py"))
    out["op_improve"] = (op > num("op_income_py")).where(op.notna() & num("op_income_py").notna())
    return out.sort_values(["code", "date"]).reset_index(drop=True)


class FinIndex:
    """날짜별 '그때 알 수 있었던' 최신 재무 지표"""

    COLS = ["op_pos", "op_margin", "roe", "debt_ratio", "current_ratio", "impaired",
            "rev_yoy", "op_yoy", "ni_yoy", "op_improve", "year", "reprt"]

    def __init__(self, metrics: pd.DataFrame):
        self.m = metrics
        self.by = {} if metrics.empty else {c: g.reset_index(drop=True) for c, g in metrics.groupby("code", sort=False)}
        # 빠른 조회용 배열 (백테스트: 하루 수백 종목 × 수백 일)
        self._arr = {c: (g["date"].values.astype("datetime64[ns]"), g[self.COLS].to_numpy(dtype=object))
                     for c, g in self.by.items()}

    @classmethod
    def from_raw(cls, fin: pd.DataFrame) -> "FinIndex":
        return cls(build_metrics(fin))

    def at(self, codes, as_of: pd.Timestamp) -> pd.DataFrame:
        t = np.datetime64(pd.Timestamp(as_of).to_datetime64(), "ns")
        limit = np.timedelta64(550, "D")
        idx, vals = [], []
        for c in codes:
            a = self._arr.get(c)
            if a is None:
                continue
            dates, v = a
            k = int(np.searchsorted(dates, t, side="left")) - 1
            if k < 0:
                continue
            if t - dates[k] > limit + np.timedelta64(1, "D") - np.timedelta64(1, "ns"):
                continue                                  # 1년 반 넘게 새 보고서가 없음 → 모름 (일수 기준 > 550)
            idx.append(c)
            vals.append(v[k])
        if not idx:
            return pd.DataFrame(columns=self.COLS)
        return pd.DataFrame(np.vstack(vals), index=idx, columns=self.COLS).infer_objects()
