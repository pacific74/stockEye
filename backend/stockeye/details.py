"""전 종목 상세 미리 만들기 (앱의 종목 화면 = 서버 없이 Supabase 에서 바로 읽기).

종목마다:  기업 개요(업종·주요제품·시총·PER) / 점수·매매계획·근거·주의 / 최근 120일 차트(이평선 5·20·60·120 포함) / 최근 30일 공시 / 설명 / (후보만) 비슷한 과거 패턴
리포트와 같은 스크리닝 결과(피처 단면)를 그대로 쓰므로 미래 데이터는 들어가지 않는다.
"""
from __future__ import annotations

import logging

import pandas as pd

from .ai.explainer import rule_based
from .engine.filters import stage2
from .engine.screener import Candidate, titles_from_view
from .engine.scoring import score_row
from .engine.trade_plan import make_plan

log = logging.getLogger(__name__)

MA_WINDOWS = (5, 20, 60, 120)


def _add_ma(df: pd.DataFrame) -> pd.DataFrame:
    """종목별 이동평균 (code, date 로 정렬된 df). 앞쪽 기간이 모자라면 NaN."""
    df = df.sort_values(["code", "date"]).reset_index(drop=True)
    g = df.groupby("code", sort=False)["close"]
    for n in MA_WINDOWS:
        df[f"ma{n}"] = g.rolling(n, min_periods=n).mean().reset_index(level=0, drop=True)
    return df


def _bars(g: pd.DataFrame) -> list[dict]:
    """일봉 → 앱 차트용 [{date, open, high, low, close, volume, ma5, ma20, ma60, ma120}]"""
    cols = [g[c].tolist() for c in ("date", "open", "high", "low", "close", "volume")]
    mas = [g[f"ma{n}"].tolist() if f"ma{n}" in g else [None] * len(g) for n in MA_WINDOWS]
    out = []
    for i, (d, o, h, lo, c, v) in enumerate(zip(*cols)):
        b = {"date": str(pd.Timestamp(d).date()), "open": float(o), "high": float(h), "low": float(lo),
             "close": float(c), "volume": float(v)}
        for n, m in zip(MA_WINDOWS, mas):
            x = m[i]
            b[f"ma{n}"] = None if x is None or pd.isna(x) else round(float(x), 1)
        out.append(b)
    return out


def _report_index(report: dict) -> dict[str, dict]:
    """리포트 후보(전략·테마 정보가 붙은 것)를 코드별로. 종합 후보 우선."""
    idx = {}
    for c in report["candidates"]:
        idx.setdefault(c["code"], c)
    for v in report["strategies"].values():
        for c in v["candidates"]:
            idx.setdefault(c["code"], c)
    return idx


def build_details(pit, cfg: dict, report: dict, res, view, chart_days: int = 120,
                  similar: bool = True, similar_top: int = 10, company: dict | None = None) -> list[dict]:
    """company = data.company.fetch_company_meta() 결과 (없으면 KRX 업종·밸류에이션만으로 개요)"""
    x, uni = res.x, res.universe
    date = report["date"]
    names = pit.listing if not pit.listing.empty else pd.DataFrame(columns=["code", "name", "market"])
    nm = names.drop_duplicates("code", keep="last").set_index("code")
    sectors = getattr(pit, "sectors", pd.DataFrame())
    sector_of = dict(zip(sectors["code"], sectors["sector"])) if not sectors.empty else {}
    in_uni = set(uni.index) if uni is not None else set()
    in_s2 = set(stage2(uni, cfg)[0].index) if uni is not None and len(uni) else set()
    titles = titles_from_view(view, x.index) or {}
    rep_idx = _report_index(report)
    expl = report.get("explanations", {})
    theme_of = {c["code"]: c.get("theme") for c in rep_idx.values()}

    # 차트: 최근 chart_days 영업일 (+ 이평선 계산용으로 그 앞 119일을 더 읽어서 계산)
    oh = view.ohlcv()
    dates = sorted(oh["date"].unique())
    warm = max(MA_WINDOWS) - 1
    oh = _add_ma(oh[oh["date"] >= dates[max(0, len(dates) - chart_days - warm)]])
    oh = oh[oh["date"] >= dates[max(0, len(dates) - chart_days)]]
    charts = {code: _bars(g) for code, g in oh.groupby("code", sort=False)}

    disc = view.disclosures(list(x.index), since_days=30) if not view._disc.empty else pd.DataFrame()
    discs = {} if disc.empty else {
        code: [{"published_at": str(t), "title": ti} for t, ti in zip(g["published_at"], g["title"])]
        for code, g in disc.sort_values("published_at", ascending=False).groupby("code", sort=False)}

    from .data.company import build_profiles
    try:
        profiles = build_profiles(view, company, sectors, names, list(x.index))
    except Exception as ex:  # noqa: BLE001  (개요는 참고용 — 실패해도 상세는 만든다)
        log.warning("기업 개요 만들기 실패: %s", ex)
        profiles = {}

    rows, failed = [], 0
    for code, r in x.iterrows():
        if code in rep_idx:
            cand = rep_idx[code]
        else:
            try:
                sr = score_row(code, r, cfg["score_weights"], titles.get(code, []) if titles else None)
                plan = make_plan(r, sr.total, sr.warnings, cfg)
            except Exception:  # noqa: BLE001  (상장 직후 등 지표가 부족한 종목)
                failed += 1
                continue
            extra = []
            if code not in in_uni:
                extra.append("1차 필터 미통과 (거래대금/가격/관리종목/급락 등)")
            elif code not in in_s2:
                extra.append("2차 필터 미통과 (추세 조건)")
            n = nm.loc[code] if code in nm.index else None
            cand = Candidate(rank=0, code=code, name=str(n["name"]) if n is not None else code,
                             market=str(n.get("market", "")) if n is not None else "",
                             score=sr.total, stars=sr.stars, parts=sr.parts, max_parts=sr.max_parts,
                             missing=sr.missing, reasons=sr.reasons, warnings=sr.warnings + extra,
                             plan=plan.to_dict()).to_dict()
            cand["sector"] = sector_of.get(code)
        e = expl.get(code)
        if e is None:
            try:
                e = {"text": rule_based(cand), "source": "rule", "model": None, "verified": True,
                     "disclaimer": "설명은 위 점수·신호를 풀어 쓴 참고용이며, 매매 신호는 통계/알고리즘 결과입니다."}
            except Exception:  # noqa: BLE001
                e = None
        rows.append({"code": code, "name": cand.get("name", code), "market": cand.get("market", ""),
                     "sector": sector_of.get(code), "date": date, "score": cand.get("score"),
                     "in_universe": code in in_uni,
                     "candidate": {**cand, "theme": theme_of.get(code, cand.get("theme")),
                                   "profile": profiles.get(code) or None},
                     "chart": charts.get(code, []), "disclosures": discs.get(code, []),
                     "explanation": e, "similar_patterns": None})
    if failed:
        log.info("지표 부족으로 상세를 만들지 못한 종목 %d개", failed)

    if similar and rep_idx:
        from .analysis.similar import PatternIndex
        log.info("비슷한 패턴 계산 (후보 %d종목)...", len(rep_idx))
        pi = PatternIndex(pit.ohlcv, window=20)
        name_of = dict(zip(names["code"], names["name"]))
        by_code = {r["code"]: r for r in rows}
        results = {}
        for code in rep_idx:
            if code not in by_code:
                continue
            try:
                s = pi.search(code, date, top=similar_top)
            except Exception as ex:  # noqa: BLE001
                s = {"error": str(ex)}
            if "error" not in s:
                for m in s["matches"]:
                    m["name"] = name_of.get(m["code"], m["code"])
                s["name"] = name_of.get(code, code)
            results[code] = s
        # 비교 화면용: 각 유사 구간의 실제 일봉 (패턴 20일 + 그 뒤 20일)
        need = {m["code"] for s in results.values() if "error" not in s for m in s["matches"]}
        oh = _add_ma(pit.ohlcv[pit.ohlcv["code"].isin(need)])
        groups = {c: g.reset_index(drop=True) for c, g in oh.groupby("code", sort=False)}
        for code, s in results.items():
            if "error" not in s:
                for m in s["matches"]:
                    g = groups.get(m["code"])
                    if g is None:
                        continue
                    pos = g.index[g["date"] == pd.Timestamp(m["start"])]
                    if len(pos) == 0:
                        continue
                    seg = g.iloc[int(pos[0]): int(pos[0]) + s["window"] + len(m.get("future", []))]
                    m["bars"] = _bars(seg)
            by_code[code]["similar_patterns"] = s
    return rows
