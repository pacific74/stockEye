"""일일 리포트 = 앱 메인 화면 데이터.

  오늘의 시장(지수·분위기) → 돈이 몰리는 업종/테마 → TOP10 → 전략별 후보 → AI 설명

매일 장 마감 후(18시 이후) 한 번 만들어 data/reports/YYYY-MM-DD.json 으로 저장하고,
API 서버와 Supabase 는 이 파일을 그대로 보여준다 (앱을 열 때마다 다시 계산하지 않음).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from .ai.explainer import Explainer
from .analysis.market import market_overview, load_themes, build_groups, group_strength
from .config import data_dir
from .data.pit import PointInTimeData
from .engine.screener import screen, default_as_of
from .engine.scoring import score_row

log = logging.getLogger(__name__)


def build_report(pit: PointInTimeData, cfg: dict, as_of=None, with_ai: bool = True) -> dict:
    return build_report_full(pit, cfg, as_of, with_ai)[0]


def build_report_full(pit: PointInTimeData, cfg: dict, as_of=None, with_ai: bool = True):
    """리포트 + 스크리닝 결과(피처 단면 포함) + PIT 뷰. 종목 상세를 미리 만들 때 같이 쓴다."""
    as_of = pd.Timestamp(as_of) if as_of else default_as_of(pit.trading_dates()[-1])
    view = pit.view(as_of)
    log.info("스크리닝 (%s 기준)...", as_of)
    res = screen(view, cfg)
    x, uni = res.x, res.universe

    # 1차 필터 통과 종목 전체의 종합 점수 (업종 대표 종목 정렬용)
    uni_scores = {code: score_row(code, r, cfg["score_weights"], None).total for code, r in uni.iterrows()}
    for c in res.candidates:
        uni_scores[c.code] = c.score

    names = pit.listing if not pit.listing.empty else pd.DataFrame(columns=["code", "name"])
    sectors = getattr(pit, "sectors", pd.DataFrame())
    groups, unmatched = build_groups(names, sectors, load_themes())
    strength = group_strength(x, groups, uni_scores, names)
    mf = cfg.get("market_filter", {})
    market = market_overview(view.index(), x, int(mf.get("ma", 60)))

    # 종목 → 소속 테마(가장 강한 것) 표시
    best_group = {}
    for g in strength:
        if g["type"] != "theme":
            continue
        for code in groups[g["group"]]["codes"]:
            best_group.setdefault(code, g)
    sector_of = dict(zip(sectors["code"], sectors["sector"])) if not sectors.empty else {}

    d = res.to_dict()
    theme_of = {c: g["group"] for c, g in best_group.items()}
    report = {
        "date": d["date"], "as_of": d["as_of"], "funnel": d["funnel"], "dropped": d["dropped"],
        "market": market, "sectors": strength, "unmatched_theme_names": unmatched,
        "labels": d["labels"], "explanations": {},
    }

    engine = (cfg.get("engine") or "v2").lower()
    if engine == "v2":
        # ---- 매수후보 V2: 시장 → 업종 → 재무·공시 위험 → 기술 → 100점 → 가격위치 → 과열 → 등급 / 매수 신호 ----
        from .engine.v2_report import evaluate_all, build_lists, market_summary
        ev = evaluate_all(pit, view, x, uni.index if uni is not None else [], cfg, as_of)
        res.v2 = ev
        name_of = dict(zip(names["code"], names["name"])) if not names.empty else {}
        L = build_lists(ev, x, name_of, theme_of)
        report.update({
            "engine": "v2",
            "top10": L["overall"][:10], "candidates": L["overall"], "strategies": L["lists"],
            "v2": {
                "market": market_summary(ev, cfg),
                "counts": {**ev[ev["stage1"]]["status"].value_counts().to_dict(),
                           "매수 신호": int(ev["signal"].sum())},
                "has_financials": bool(ev.attrs.get("has_fin")), "has_disclosures": bool(ev.attrs.get("has_disc")),
            },
        })
        targets = L["overall"][: cfg.get("ai", {}).get("explain_top", 20)]
        # ---- V3 기준 전략 (🔒 고정 규칙): 오늘 V3B 상위 10 ----
        try:
            from .engine.v3_report import build_section
            v3s = build_section(pit, x, ev, name_of, theme_of, as_of)
            # 앱·알림·발행은 V3 만: TOP 10 = V3B 상위 10 / 목록 = V3 기준 하나 (V2 는 자격 판정 재료로 내부에서만 씀)
            v3c = v3s["list"]["candidates"]
            report.update({"top10": v3c, "candidates": v3c, "strategies": {"v3": v3s["list"]}})
            report["v3"] = v3s["meta"]
            res.v3_eligible = v3s["eligible"]
            res.v3_scores = v3s["scores"]
            targets = []          # AI 설명은 V2 항목 기준이라 끔 → 종목 상세에 V3 규칙 문장
        except Exception as e:  # noqa: BLE001  V3 가 실패해도 V2 리포트는 그대로
            log.warning("V3 기준 전략 계산 실패: %s", e)
    else:
        # ---- (예전) V1: 종합 점수 + 전략 A~E ----
        weak = weak_markets(market, cfg)
        for c in d["candidates"] + [c for v in d["strategies"].values() for c in v["candidates"]]:
            g = best_group.get(c["code"])
            c["theme"] = g["group"] if g else None
            c["sector"] = sector_of.get(c["code"])
            apply_market_filter(c, weak, market.get("filter_ma", 60))
        report.update({"engine": "v1", "top10": d["candidates"][:10], "candidates": d["candidates"],
                       "strategies": d["strategies"]})
        targets = list(d["candidates"][: cfg.get("ai", {}).get("explain_top", 20)])
        for v in d["strategies"].values():
            targets += v["candidates"][:2]

    # ---- AI 설명 (상위 후보) ----
    if with_ai:
        ex = Explainer(cfg, data_dir(cfg) / "ai_cache")
        seen = set()
        for c in targets:
            if c["code"] in seen:
                continue
            seen.add(c["code"])
            g = best_group.get(c["code"])
            report["explanations"][c["code"]] = ex.explain(c, d["date"], market, g)
        log.info("설명 %d건 (%s)", len(report["explanations"]),
                 "AI" if ex.enabled else "규칙 기반 — ANTHROPIC_API_KEY 없음")
    return report, res, view


def weak_markets(market: dict, cfg: dict) -> set[str]:
    """시장 필터: 지수가 N일선 아래인 시장 {'KOSPI', 'KOSDAQ'}"""
    if not cfg.get("market_filter", {}).get("enabled", True):
        return set()
    return {i["code"] for i in market.get("indices", []) if i.get("above_ma_filter") is False}


def apply_market_filter(c: dict, weak: set[str], ma: int = 60) -> dict:
    """약세 시장 종목: '매수 고려/눌림 대기' → '관망' + 경고 (실전 매매 엔진·알림도 이 판정을 따른다)"""
    m = c.get("market")
    if m not in weak or c.get("market_weak"):
        return c
    name = {"KOSPI": "코스피", "KOSDAQ": "코스닥"}.get(m, m)
    c["market_weak"] = True
    c["warnings"] = [f"시장 약세: {name} 지수가 {ma}일선 아래 → 신규 매수 쉬기"] + list(c.get("warnings") or [])
    plan = c.get("plan") or {}
    if plan.get("verdict") in ("매수 고려", "눌림 대기"):
        plan["verdict_before_filter"] = plan["verdict"]
        plan["verdict"] = "관망"
        plan["verdict_reason"] = (f"{name} 지수가 {ma}일선 아래(시장 약세) — 지수가 회복할 때까지 신규 매수 쉬기 "
                                  f"(시장 필터 전 판정: {plan['verdict_before_filter']})")
    return c


def save_report(report: dict, cfg: dict) -> Path:
    out = data_dir(cfg) / "reports"
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"{report['date']}.json"
    txt = json.dumps(report, ensure_ascii=False, default=str)
    p.write_text(txt, encoding="utf-8")
    (out / "latest.json").write_text(txt, encoding="utf-8")
    return p


def load_latest(cfg: dict) -> dict | None:
    p = data_dir(cfg) / "reports" / "latest.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
