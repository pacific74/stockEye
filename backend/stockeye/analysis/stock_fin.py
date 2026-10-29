"""종목 상세 '실적·외국인' — 매출액 · 영업이익 · 외국인 보유율 (2026-10-29)

  매출액·영업이익   DART 주요계정(financials) — 연결(CFS) 우선. 두 줄:
                    ① 최근 연간(사업보고서) ② 그보다 새로운 분기 보고서가 있으면 그 누적(1분기·반기·3분기) — 단위 억원
  외국인 보유율     KRX(pykrx) 외국인 지분율(%) — 조회가 안 되면(KRX 장애 등) 그 칸만 비움
  발행              system_status 'stock_fin' {date, rows: {code: [매출억, 영업이익억, 라벨, 매출억2, 영업이익억2, 라벨2, 외인%]}}
  앱 종목 상세 화면에서만 읽음. 참고용 정보이며 점수 계산에는 쓰지 않음
"""
from __future__ import annotations

import logging

import pandas as pd

log = logging.getLogger(__name__)

ORDER = {"Q1": 1, "H1": 2, "Q3": 3, "FY": 4}
LABEL = {"Q1": "1분기", "H1": "반기", "Q3": "3분기", "FY": "연간"}


def _eok(v) -> int | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else int(round(f / 1e8))


def fin_rows(fin: pd.DataFrame | None) -> dict[str, list]:
    """financials → {code: [매출억, 영업이익억, '2025 연간', 매출억2, 영업이익억2, '2026 3분기 누적']} (②는 없으면 None)"""
    if fin is None or len(fin) == 0 or "reprt" not in fin:
        return {}
    d = fin.copy()
    d["_o"] = d["reprt"].map(ORDER)
    d = d.dropna(subset=["_o", "year"])
    if "fs" in d:                                                    # 같은 보고서에 연결·별도가 있으면 연결
        d["_c"] = (d["fs"] == "CFS").astype(int)
        d = d.sort_values(["code", "year", "_o", "_c"]).drop_duplicates(["code", "year", "_o"], keep="last")
    out: dict[str, list] = {}
    for code, g in d.groupby("code"):
        fy = g[g["reprt"] == "FY"].sort_values("year")
        row = [None, None, None, None, None, None]
        if len(fy):
            r = fy.iloc[-1]
            row[:3] = [_eok(r.get("revenue")), _eok(r.get("op_income")), f"{int(r['year'])} 연간"]
        last = g.sort_values(["year", "_o"]).iloc[-1]
        if last["reprt"] != "FY" and (not len(fy) or (int(last["year"]), last["_o"]) > (int(fy.iloc[-1]["year"]), 4)):
            row[3:] = [_eok(last.get("revenue")), _eok(last.get("op_income")), f"{int(last['year'])} {LABEL[last['reprt']]} 누적"]
        if any(v is not None for v in row[:2] + row[3:5]):
            out[str(code).zfill(6)] = row
    return out


def foreign_ratio(date) -> dict[str, float]:
    """외국인 지분율 {code: %} (pykrx 전 종목 한 번). 실패하면 빈 dict"""
    try:
        from pykrx import stock
        df = stock.get_exhaustion_rates_of_foreign_investment(pd.Timestamp(date).strftime("%Y%m%d"), market="ALL")
        col = next((c for c in df.columns if "지분율" in str(c)), None)
        if col is None:
            return {}
        return {str(c).zfill(6): round(float(v), 2) for c, v in df[col].items() if pd.notna(v) and float(v) > 0}
    except Exception as e:  # noqa: BLE001
        log.warning("외국인 지분율 조회 실패(%s) → 그 칸 생략", e)
        return {}


def build(fin: pd.DataFrame | None, frgn: dict[str, float]) -> dict[str, list]:
    rows = fin_rows(fin)
    for code in set(rows) | set(frgn):
        r = rows.setdefault(code, [None] * 6)
        r.append(frgn.get(code))
    return rows


def run(sb, fin: pd.DataFrame | None, date) -> int:
    from ..cloud import publish as pub
    rows = build(fin, foreign_ratio(date))
    if rows:
        pub.publish_status(sb, "stock_fin", {"date": str(date)[:10], "rows": rows})
    return len(rows)
