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


EXP_TABS = ("nextday", "early", "reversal")     # 점수 체계가 다른 실험 탭 (기본 후보로는 안 쓰고 상세에 따로 붙임)


def is_experimental(key: str, lst: dict | None) -> bool:
    """후보 메뉴의 실험 탭인지 — 새 탭은 목록에 experimental=True 만 넣으면 됨"""
    return key in EXP_TABS or bool((lst or {}).get("experimental"))


def _report_index(report: dict) -> dict[str, dict]:
    """리포트 후보(전략·테마 정보가 붙은 것)를 코드별로. 종합 후보 우선."""
    idx = {}
    for c in report["candidates"]:
        idx.setdefault(c["code"], c)
    for k, v in report["strategies"].items():
        if is_experimental(k, v):   # 실험 탭은 점수 체계가 달라 기본 후보로 쓰지 않음 (상세에 따로 붙임)
            continue
        for c in v["candidates"]:
            idx.setdefault(c["code"], c)
    return idx


def build_details(pit, cfg: dict, report: dict, res, view, chart_days: int = 120,
                  similar: bool = True, similar_top: int = 10, company: dict | None = None,
                  similar_codes=None) -> list[dict]:
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
    nd_idx = {c["code"]: c.get("nextday") for c in (report.get("strategies", {}).get("nextday") or {}).get("candidates", [])}
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
    from .report import apply_market_filter, weak_markets
    weak = weak_markets(report.get("market", {}), cfg)
    try:
        profiles = build_profiles(view, company, sectors, names, list(x.index))
    except Exception as ex:  # noqa: BLE001  (개요는 참고용 — 실패해도 상세는 만든다)
        log.warning("기업 개요 만들기 실패: %s", ex)
        profiles = {}

    v2ev = getattr(res, "v2", None)          # V2 엔진이면 리포트가 전 종목을 이미 평가해 둠
    if v2ev is not None:
        from .engine.v2_report import candidate_dict
        bg_theme = {c["code"]: c.get("theme") for c in rep_idx.values()}

    rows, failed = [], 0
    for code, r in x.iterrows():
        if code in rep_idx:
            cand = rep_idx[code]
        elif v2ev is not None:
            if code not in v2ev.index:
                failed += 1
                continue
            n = nm.loc[code] if code in nm.index else None
            cand = candidate_dict(code, v2ev.loc[code], r, str(n["name"]) if n is not None else code, 0,
                                  bg_theme.get(code))
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
            apply_market_filter(cand, weak, report.get("market", {}).get("filter_ma", 60))
        v3s = getattr(res, "v3_scores", None)
        v3text = None
        if v3s is not None:
            from .engine.v3_report import apply as v3_apply
            if code in v3s.index:
                cand = v3_apply(cand, v3s.loc[code])         # 점수 = V3B 100점 환산, 판정·근거·주의 = V3
                v3text = cand["v3"].get("text")
            else:
                cand = {**cand, "score": None, "reasons": [], "tags": [],
                        "warnings": ["1차 필터 미통과 (거래대금·가격·관리종목·급락 등)"],
                        "plan": {**(cand.get("plan") or {}), "verdict": "V3 자격 없음",
                                 "verdict_reason": "1차 필터 미통과", "reference_only": True},
                        "v3": {"status": "자격 없음", "why_not": ["1차 필터 미통과 (거래대금·가격·관리종목·급락 등)"],
                               "version": None}}
                v3text = "1차 필터(거래대금·가격·관리종목·급락)를 통과하지 못해 V3 점수를 매기지 않았습니다."
        rvs = getattr(res, "rev_scores", None)
        if rvs is not None and code in rvs.index:
            from .engine.reversal_report import info as rev_info
            cand = {**cand, "reversal": rev_info(rvs.loc[code])}
        ups = getattr(res, "early_scores", None)
        if ups is not None and code in ups.index:
            from .engine.early_report import info as up_info
            cand = {**cand, "early": up_info(ups.loc[code])}
        nds = getattr(res, "nextday_scores", None)
        if nds is not None and code in nds.index:
            from .engine.nextday_report import info as nd_info
            cand = {**cand, "nextday": nd_info(nds.loc[code])}
        elif code in nd_idx:                     # 장중: 전날 장 마감 점수 + 지금 상태
            cand = {**cand, "nextday": nd_idx[code]}
        e = expl.get(code) if v3s is None else None
        # 요약 설명: 보조지표·이평선·거래량·수급·지지/저항 기준 (V3 점수 설명은 candidate.v3.text 로 따로 남음)
        try:
            from .analysis.tech_summary import summarize
            ts = summarize(r, cand.get("plan") or {})
            e = {"text": ts["text"], "points": ts["points"], "tone": ts["tone"], "source": "rule", "model": None,
                 "verified": True, "disclaimer": "보조지표를 풀어 쓴 참고용 설명이며 투자 권유가 아닙니다."}
        except Exception as ex:  # noqa: BLE001
            log.debug("지표 요약 실패 %s: %s", code, ex)
            if v3text:
                e = {"text": v3text, "source": "rule", "model": None, "verified": True,
                     "disclaimer": "V3B 점수와 규칙을 풀어 쓴 참고용 설명이며 투자 권유가 아닙니다."}
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

    # 비슷한 패턴: 리포트 후보 + 회원들의 보유종목 (similar_codes)
    # 후보 메뉴의 모든 탭 후보 (새 탭이 생기면 자동 포함 — 리포트 strategies 에 있는 목록 전부)
    exp_codes = [c["code"] for v in (report.get("strategies") or {}).values() for c in (v or {}).get("candidates", [])]
    base = list(dict.fromkeys(list(rep_idx) + exp_codes))
    sim_targets = list(dict.fromkeys(base + [c for c in (similar_codes or []) if c]))
    if similar and sim_targets:
        from .analysis.similar import PatternIndex
        log.info("비슷한 패턴 계산 (후보 %d [V3 %d + 실험 탭 %d] + 보유 %d종목)...", len(base), len(rep_idx),
                 len(base) - len(rep_idx), len(sim_targets) - len(base))
        pi = PatternIndex(pit.ohlcv, window=20)
        name_of = dict(zip(names["code"], names["name"]))
        by_code = {r["code"]: r for r in rows}
        results = similar_payloads(pi, [c for c in sim_targets if c in by_code], date, pit.ohlcv, name_of, similar_top)
        for code, s_ in results.items():
            by_code[code]["similar_patterns"] = s_
    return rows


def similar_payloads(pi, codes, date, ohlcv: pd.DataFrame, name_of: dict, top: int = 10) -> dict:
    """종목별 비슷한 패턴 + 비교 화면용 실제 일봉(패턴 20일 + 그 뒤 20일). 저녁 배치·검색 요청 처리 공용"""
    results = {}
    for code in codes:
        try:
            s = pi.search(code, date, top=top)
        except Exception as ex:  # noqa: BLE001
            s = {"error": str(ex)}
        if "error" not in s:
            for m in s["matches"]:
                m["name"] = name_of.get(m["code"], m["code"])
            s["name"] = name_of.get(code, code)
        results[code] = s
    need = {m["code"] for s in results.values() if "error" not in s for m in s["matches"]}
    oh = _add_ma(ohlcv[ohlcv["code"].isin(need)])
    groups = {c: g.reset_index(drop=True) for c, g in oh.groupby("code", sort=False)}
    for code, s in results.items():
        if "error" in s:
            continue
        for m in s["matches"]:
            g = groups.get(m["code"])
            if g is None:
                continue
            pos = g.index[g["date"] == pd.Timestamp(m["start"])]
            if len(pos) == 0:
                continue
            seg = g.iloc[int(pos[0]): int(pos[0]) + s["window"] + len(m.get("future", []))]
            m["bars"] = _bars(seg)
    return results
