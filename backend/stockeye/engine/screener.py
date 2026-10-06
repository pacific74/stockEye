"""종목 선정 엔진 파이프라인.

   전체(~4,000) ─1차 필터→ ~500 ─2차 필터→ 50~100 ─수급·뉴스 포함 100점→ 순위 + 매매계획
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..data.pit import PITView, DECISION_TIME, at
from ..indicators import compute_features
from .filters import stage1, stage2
from .scoring import score_row, LABELS
from .trade_plan import make_plan, strategy_verdict
from .strategies import STRATEGIES, LIMITATIONS, select as strategy_select


@dataclass
class Candidate:
    rank: int
    code: str
    name: str
    market: str
    score: float
    stars: int
    parts: dict
    max_parts: dict
    missing: list
    reasons: list
    warnings: list
    plan: dict
    strategy: str = ""                 # 전략 후보일 때 전략 키 (A~E)
    strategy_score: float | None = None
    strategy_reasons: list = field(default_factory=list)
    tags: list = field(default_factory=list)   # 이 종목이 해당되는 전략 키 목록

    def to_dict(self):
        return self.__dict__.copy()


@dataclass
class ScreenResult:
    as_of: str
    date: str
    funnel: list = field(default_factory=list)     # [(단계, 종목수)]
    dropped: dict = field(default_factory=dict)    # 단계별 탈락 사유
    candidates: list = field(default_factory=list)                 # 종합 점수 순 (상승 후보)
    strategies: dict = field(default_factory=dict)                 # 전략 키 → [Candidate]
    x: pd.DataFrame | None = field(default=None, repr=False)       # 그날 피처 단면 (직렬화 안 함)
    universe: pd.DataFrame | None = field(default=None, repr=False)  # 1차 필터 통과 단면

    def to_dict(self):
        return {"as_of": self.as_of, "date": self.date, "funnel": self.funnel, "dropped": self.dropped,
                "candidates": [c.to_dict() for c in self.candidates], "labels": LABELS,
                "strategies": {k: {"name": STRATEGIES[k].name, "short": STRATEGIES[k].short,
                                   "description": STRATEGIES[k].description, "limitation": LIMITATIONS.get(k),
                                   "candidates": [c.to_dict() for c in v]}
                               for k, v in self.strategies.items()}}

    def find(self, code: str):
        for c in self.candidates:
            if c.code == code:
                return c
        for v in self.strategies.values():
            for c in v:
                if c.code == code:
                    return c
        return None


def screen_cross_section(x: pd.DataFrame, listing: pd.DataFrame, titles: dict[str, list] | None,
                         cfg: dict, date, as_of, names: pd.DataFrame | None = None,
                         with_strategies: bool = True) -> ScreenResult:
    """x: 하루치 피처 (index=code). titles: 코드→최근 공시 제목 (None 이면 공시 데이터 없음)."""
    res = ScreenResult(as_of=str(as_of), date=str(pd.Timestamp(date).date()))
    res.funnel.append(("전체", len(x)))
    s1, d1 = stage1(x, listing, cfg)
    res.funnel.append(("1차 필터", len(s1)))
    s2, d2 = stage2(s1, cfg)
    res.funnel.append(("2차 필터", len(s2)))
    res.dropped = {"1차": d1, "2차": d2}

    # 종목명은 미래참조와 무관 → 최신 목록을 써도 됨 (관리종목 여부는 listing=PIT 기준)
    src = names if names is not None and not names.empty else listing
    names = (src.drop_duplicates("code", keep="last").set_index("code")
             if not src.empty else pd.DataFrame())

    def build(code, r, rank, extra=None):
        t = None if titles is None else titles.get(code, [])
        sr = score_row(code, r, cfg["score_weights"], t)
        plan = make_plan(r, sr.total, sr.warnings, cfg)
        nm = names.loc[code] if code in names.index else None
        c = Candidate(
            rank=rank, code=code,
            name=str(nm["name"]) if nm is not None else code,
            market=str(nm["market"]) if nm is not None and "market" in nm else "",
            score=sr.total, stars=sr.stars, parts=sr.parts, max_parts=sr.max_parts, missing=sr.missing,
            reasons=sr.reasons, warnings=sr.warnings, plan=plan.to_dict())
        if extra:
            for k, v in extra.items():
                setattr(c, k, v)
            c.plan["verdict"], c.plan["verdict_reason"] = strategy_verdict(
                c.plan, c.strategy, c.strategy_score, c.score, c.warnings)
        return c

    # ---- 종합(상승 후보): 2차 필터 + 100점 ----
    scored = []
    for code, r in s2.iterrows():
        t = None if titles is None else titles.get(code, [])
        scored.append((score_row(code, r, cfg["score_weights"], t).total, code, r))
    scored.sort(key=lambda z: z[0], reverse=True)
    for i, (_, code, r) in enumerate(scored[: cfg["stage2"]["max_candidates"]], 1):
        res.candidates.append(build(code, r, i))
    res.funnel.append(("최종 후보", len(res.candidates)))

    # ---- 전략별 후보: 1차 필터 통과 종목에서 각 전략 조건 ----
    per = cfg.get("strategies", {}).get("max_per_strategy", 30)
    tags: dict[str, list] = {}
    for key, st in (STRATEGIES.items() if with_strategies else []):
        sel = strategy_select(key, s1)
        lst = []
        for code, r in sel.head(per * 2).iterrows():
            c = build(code, r, 0, {"strategy": key, "strategy_score": float(r["strategy_score"]),
                                   "strategy_reasons": st.reasons(r)})
            lst.append(c)
            tags.setdefault(code, []).append(key)
        # 정렬: 전략 점수 60% + 종합 점수 40%
        lst.sort(key=lambda c: 0.6 * c.strategy_score + 0.4 * c.score, reverse=True)
        for i, c in enumerate(lst[:per], 1):
            c.rank = i
        res.strategies[key] = lst[:per]
    for c in res.candidates + [c for v in res.strategies.values() for c in v]:
        c.tags = tags.get(c.code, [])
    res.x, res.universe = x, s1
    return res


def titles_from_view(view: PITView, codes, days: int = 5) -> dict[str, list] | None:
    if view._disc.empty:
        return None
    d = view.disclosures(list(codes), since_days=days)
    return d.groupby("code")["title"].apply(list).to_dict()


def screen(view: PITView, cfg: dict, history_days: int | None = None) -> ScreenResult:
    """실전(매일) 스크리닝: as_of 시점 PIT 뷰에서 직접 피처를 계산 → 미래 데이터가 구조적으로 불가능."""
    history_days = history_days or cfg["data"]["history_days"]
    oh = view.ohlcv()
    if oh.empty:
        raise ValueError("데이터 없음: 먼저 수집을 실행하세요")
    dates = sorted(oh["date"].unique())
    last = pd.Timestamp(dates[-1])
    start = pd.Timestamp(dates[max(0, len(dates) - history_days)])
    oh = oh[oh["date"] >= start]
    fl = view.flows()
    fd = view.fundamentals()
    feat = compute_features(oh, fl[fl["date"] >= start] if not fl.empty else None,
                            fd[fd["date"] >= start] if not fd.empty else None)
    x = feat.xs(last, level="date")
    titles = titles_from_view(view, x.index)
    return screen_cross_section(x, view.listing(), titles, cfg, last, view.as_of, names=view._listing)


def default_as_of(date) -> pd.Timestamp:
    return at(date, DECISION_TIME)


def analyze_one(view: PITView, code: str, cfg: dict, names: pd.DataFrame | None = None,
                history_days: int = 400) -> dict | None:
    """후보 목록에 없는 종목도 같은 방식으로 점수·매매계획을 계산 (검색해서 볼 때)."""
    oh = view.ohlcv(code)
    if oh.empty:
        return None
    oh = oh.sort_values("date").tail(history_days)
    fl, fd = view.flows(code), view.fundamentals(code)
    feat = compute_features(oh, fl if not fl.empty else None, fd if not fd.empty else None)
    last = feat.index.get_level_values("date").max()
    x = feat.xs(last, level="date")
    titles = titles_from_view(view, [code])
    # 필터와 무관하게 점수/계획은 보여준다
    r = x.loc[code]
    sr = score_row(code, r, cfg["score_weights"], None if titles is None else titles.get(code, []))
    plan = make_plan(r, sr.total, sr.warnings, cfg)
    nm = names.set_index("code").loc[code] if names is not None and code in set(names["code"]) else None
    s1, _ = stage1(x, view.listing(), cfg)
    s2, _ = stage2(s1, cfg) if len(s1) else (s1, {})
    return Candidate(rank=0, code=code, name=str(nm["name"]) if nm is not None else code,
                     market=str(nm.get("market", "")) if nm is not None else "",
                     score=sr.total, stars=sr.stars, parts=sr.parts, max_parts=sr.max_parts, missing=sr.missing,
                     reasons=sr.reasons, warnings=sr.warnings + ([] if len(s1) else ["1차 필터 미통과 (거래대금/가격/관리종목 등)"])
                     + ([] if len(s1) == 0 or len(s2) else ["2차 필터 미통과 (추세 조건)"]),
                     plan=plan.to_dict()).to_dict()
