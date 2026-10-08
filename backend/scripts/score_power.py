"""점수 예측력 검증 리포트 — 종합점수·항목별 점수 구간마다 5/10/20/40일 평균·중앙값·승률·일평균·최대손실

  python -m scripts.score_power --start 2021-07-01 --end 2024-12-31            # 매 거래일
  python -m scripts.score_power --start 2025-01-01 --every 5                   # 5거래일마다 (빠르게)
  → data/reports/score_power_<시작>_<끝>.md / .json

점수는 그날 18:00 시점까지 공개된 정보로만 계산 (재무·공시 포함, 미래참조 없음).
대상: 1차 필터(거래대금·가격·거래정지·관리종목·급락) 통과 종목 전체.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time

import pandas as pd

from stockeye.analysis.score_power import HORIZONS, default_bins, forward_returns, report, to_markdown
from stockeye.config import data_dir, load_config
from stockeye.data.store import DataStore

log = logging.getLogger("stockeye.score_power")

V2_COLS = {"score": [0, 40, 50, 60, 70, 80, 101],
           "trend": default_bins(20), "volume": default_bins(10), "value": default_bins(5), "flow": default_bins(15),
           "position": default_bins(15), "risk": default_bins(5), "financial": default_bins(15), "news": default_bins(15)}
LABELS = {"score": "종합점수", "trend": "추세(20)", "volume": "거래량(10)", "value": "거래대금(5)", "flow": "수급(15)",
          "position": "가격위치(15)", "risk": "변동성·위험(5)", "financial": "재무(15)", "news": "공시(15)"}


def score_panel(store: DataStore, cfg: dict, start, end, every: int = 1) -> pd.DataFrame:
    """매 거래일(every 간격) 1차 필터 통과 종목의 V2 점수·항목 점수"""
    from stockeye.data.pit import PointInTimeData, at, DECISION_TIME
    from stockeye.data.financials import FinIndex
    from stockeye.engine.filters import stage1
    from stockeye.engine.disclosure_rules import DisclosureIndex
    from stockeye.engine.v2 import V2Context, evaluate, market_states
    from stockeye.indicators import compute_features
    pit = PointInTimeData.from_store(store)
    feat = compute_features(pit.ohlcv, pit.flows, pit.fund)
    lst = pit.listing
    sec = store.load("sectors")
    fin = store.load("financials")
    ctx_fin = FinIndex.from_raw(fin) if len(fin) else None
    ctx_disc = DisclosureIndex.build(pit.disc) if len(pit.disc) else None
    states = market_states(pit.index)
    market_of = dict(zip(lst["code"], lst["market"])) if not lst.empty else {}
    sector_of = dict(zip(sec["code"], sec["sector"])) if not sec.empty else {}
    dates = feat.index.get_level_values("date").unique().sort_values()
    dates = dates[(dates >= pd.Timestamp(start)) & (dates <= pd.Timestamp(end))][::every]
    rows = []
    for d in dates:
        x = feat.xs(d, level="date")
        s1, _ = stage1(x, pit.view(at(d, DECISION_TIME)).listing(), cfg)
        if s1.empty:
            continue
        ev = evaluate(s1, V2Context(d, market_of, states, sector_of, ctx_fin, ctx_disc), cfg, detail=False)
        df = ev[list(V2_COLS)].copy()
        df["date"] = d
        rows.append(df.reset_index())
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def build(panel: pd.DataFrame, ohlcv: pd.DataFrame, cols: dict, labels: dict, title: str) -> tuple[str, dict]:
    fwd = forward_returns(ohlcv[["date", "code", "low", "close"]])
    df = panel.merge(fwd, on=["date", "code"], how="left")
    rep = report(df, cols)
    rep = {labels.get(k, k): v for k, v in rep.items()}
    md = to_markdown(rep, title)
    js = {k: {"monotonic20": v["monotonic20"], "monotonic5": v["monotonic5"],
              "table": json.loads(v["table"].to_json(orient="index", force_ascii=False))} for k, v in rep.items()}
    return md, js


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2021-07-01")
    ap.add_argument("--end", default=None, help="기본: 40거래일 전까지 (40일 수익률이 나오도록)")
    ap.add_argument("--every", type=int, default=1, help="며칠마다 점수를 매길지 (1 = 매 거래일)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    logging.getLogger("stockeye").setLevel(logging.INFO)
    t0 = time.time()
    cfg = load_config()
    store = DataStore(data_dir(cfg))
    oh = store.load("ohlcv")
    end = args.end or str(sorted(oh["date"].unique())[-max(HORIZONS) - 1])[:10]
    panel = score_panel(store, cfg, args.start, end, args.every)
    title = f"점수 예측력 {args.start} ~ {end} (신호일 종가 기준, {panel['date'].nunique()}일 · {len(panel):,}건)"
    md, js = build(panel, oh, V2_COLS, LABELS, title)
    out = data_dir(cfg) / "reports"
    out.mkdir(parents=True, exist_ok=True)
    stem = out / f"score_power_{args.start}_{end}"
    stem.with_suffix(".md").write_text(md, encoding="utf-8")
    stem.with_suffix(".json").write_text(json.dumps(js, ensure_ascii=False, indent=1), encoding="utf-8")
    print(md)
    print(f"\n저장: {stem}.md / .json ({(time.time() - t0) / 60:.1f}분)")


if __name__ == "__main__":
    main()
