"""주간 백테스트 (클라우드): 매수후보 V2 엔진을 5년치로 검증 → 앱의 백테스트 화면(관리자)에 발행.

  python -m scripts.cloud_backtest              # V2
  python -m scripts.cloud_backtest --only A,D   # (예전) V1 전략
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

from stockeye.config import load_config, data_dir
from stockeye.data.store import DataStore
from stockeye.data.pit import PointInTimeData
from stockeye.backtest.engine import Backtester
from stockeye.backtest.strategy import NamedStrategy, ScreenerStrategy
from stockeye.backtest.lookahead import audit
from stockeye.engine.strategies import STRATEGIES
from stockeye.cloud.client import Supabase
from stockeye.cloud.sync import DataSync
from stockeye.cloud import publish as pub

log = logging.getLogger("stockeye.cloud_backtest")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="예: A,D  (engine = 종합 엔진)")
    ap.add_argument("--min-score", type=float, default=75)
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    logging.getLogger("stockeye").setLevel(logging.INFO)

    cfg = load_config()
    store = DataStore(data_dir(cfg))
    sb = Supabase()
    DataSync(store, sb).pull()
    pit = PointInTimeData.from_store(store)
    t0 = time.time()
    log.info("지표 계산 중 (전 종목 × 전 기간)...")
    if not args.only:
        from stockeye.backtest.engine_v2 import BacktesterV2
        from stockeye.indicators import compute_features
        feat = compute_features(pit.ohlcv, pit.flows, pit.fund)
        res = BacktesterV2(pit, cfg, feat).run()
        d = res.to_dict()
        pub.publish_backtest(sb, "V2", "매수후보 V2 엔진", d)
        m = d["metrics"]
        log.info("[V2] %s회 승률 %s%% 기대값 %s%% PF %s 총 %s%% MDD %s%% (%.0f분)", m.get("trades"), m.get("win_rate"),
                 m.get("expectancy_pct"), m.get("profit_factor"), m.get("total_return_pct"), m.get("mdd_pct"),
                 (time.time() - t0) / 60)
        pub.process_backtest_requests(sb, pit, cfg, limit=5, features=feat)
        pub.publish_status(sb, "backtest", {"done": ["V2"], "minutes": round((time.time() - t0) / 60, 1)})
        return
    bt = Backtester(pit, cfg)
    keys = args.only.split(",")
    done = []
    for k in keys:
        strat = ScreenerStrategy(cfg, args.min_score) if k == "engine" else NamedStrategy(k, cfg)
        name = "종합 엔진" if k == "engine" else STRATEGIES[k].name
        t = time.time()
        res = bt.run(strat)
        res.audit = audit(pit, bt.features, strat, res.trades).to_dict()
        d = res.to_dict()
        pub.publish_backtest(sb, k, name, d)
        m = d["metrics"]
        log.info("[%s] %s: %s회 승률 %s%% 기대값 %s%% 총 %s%% · 미래참조 검사 %s (%.0f초)", k, name, m.get("trades"),
                 m.get("win_rate"), m.get("expectancy_pct"), m.get("total_return_pct"),
                 "통과" if res.audit.get("passed") else "실패", time.time() - t)
        done.append(k)
    pub.process_backtest_requests(sb, pit, cfg, limit=5, bt=bt)
    pub.publish_status(sb, "backtest", {"done": done, "minutes": round((time.time() - t0) / 60, 1)})


if __name__ == "__main__":
    main()
