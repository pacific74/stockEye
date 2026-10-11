"""주간 백테스트 (클라우드): V3 기준 전략 검증(선정력·매매 분리) + 매수후보 V2 엔진 → 앱의 백테스트 화면(관리자)에 발행.

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


def run_hitrate(sb, pit, cfg, tabs=None, years=None, v3_entries=None) -> dict:
    """관심종목 적중률 (탭별 매일 상위 3 → 1·2·3차 목표/손절, 연도·분기별) → backtests 'HIT'.
    탭·연도 일부만 돌리면 이전 결과에 그 부분만 덮어씀"""
    from stockeye.analysis import hitrate
    tabs = tabs or list(hitrate.TABS)
    if "v3" in tabs and v3_entries is None:                   # V3 는 매일 상위 3 (과거 선정 다시 계산)
        from stockeye.indicators import compute_features
        from stockeye.engine.v3_report import history_entries
        feat = compute_features(pit.ohlcv, pit.flows, pit.fund)
        v3_entries = history_entries(pit, cfg, feat, every=1)
        del feat
    new = hitrate.run(pit, v3_entries=v3_entries, tabs=tabs, years=years)
    old = None
    if years or len(tabs) < len(hitrate.TABS):
        try:
            rows = sb.select("backtests", {"select": "payload", "key": "eq.HIT"})
            old = rows[0]["payload"] if rows else None
        except Exception as e:  # noqa: BLE001
            log.warning("이전 적중률 읽기 실패: %s", e)
    out = hitrate.merge(old, new)
    pub.publish_backtest(sb, "HIT", "관심종목 적중률", out)
    for t, v in out["tabs"].items():
        log.info("[적중률] %s: %s건 승률 %s%%", v["name"], v["total"].get("n"), v["total"].get("win"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="예: A,D (engine) · VALID = 상세 검증만 · HIT = 적중률만 "
                                   "(HIT:nextday,early / HIT:2024,2025 / HIT:nextday:2024 처럼 탭·연도 일부)")
    ap.add_argument("--min-score", type=float, default=75)
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    logging.getLogger("stockeye").setLevel(logging.INFO)

    cfg = load_config()
    store = DataStore(data_dir(cfg))
    sb = Supabase()
    sync = DataSync(store, sb)
    sync.pull()
    pit = PointInTimeData.from_store(store)
    t0 = time.time()
    log.info("지표 계산 중 (전 종목 × 전 기간)...")
    if args.only and args.only.upper().startswith("HIT"):   # 관심종목 적중률만 (탭·연도 일부 가능)
        toks = [t.strip() for t in args.only.replace(":", ",").split(",")[1:] if t.strip()]
        years = [int(t) for t in toks if t.isdigit()]
        tabs = [t for t in toks if not t.isdigit()] or None
        run_hitrate(sb, pit, cfg, tabs=tabs, years=years or None)
        log.info("적중률 %.0f분", (time.time() - t0) / 60)
        return
    if args.only == "VALID":                      # 관심종목 검증만 (V3 과거 선정 + 4개 탭)
        from stockeye.indicators import compute_features
        from stockeye.engine.v3_report import history_entries
        from stockeye.analysis import validation
        feat = compute_features(pit.ohlcv, pit.flows, pit.fund)
        ent = history_entries(pit, cfg, feat)
        del feat
        val = validation.run(pit, v3_entries=ent)
        pub.publish_backtest(sb, "VALID", "관심종목 검증", val)
        for st_ in val["strategies"]:
            log.info("[검증] %s: %s", st_["name"], st_["verdict"]["label"])
        log.info("관심종목 검증 %.0f분", (time.time() - t0) / 60)
        return
    if not args.only:
        from stockeye.backtest.engine_v2 import BacktesterV2
        from stockeye.indicators import compute_features
        feat = compute_features(pit.ohlcv, pit.flows, pit.fund)
        # ---- V3 기준 전략 검증: ① 종목 선정력 ② 실제 매매 (기간별, 고정 이후 포함) ----
        ent = None
        try:
            from stockeye.engine.v3_report import history_entries, validate, LOG_KEY
            t3 = time.time()
            ent = history_entries(pit, cfg, feat)
            try:
                flog = sync.get_json(LOG_KEY)
            except Exception:  # noqa: BLE001
                flog = None
            v = validate(pit, ent, flog)
            pub.publish_backtest(sb, "V3B", "V3 기준 전략 검증", {**v, "start": ent[0]["date"] if ent else None,
                                                              "end": ent[-1]["date"] if ent else None, "metrics": {}})
            for pr in v["periods"]:
                log.info("[V3B] %s: 매매 %s · 기대값 %s%% · PF %s · MDD %s%% · 20일 초과 %s%%", pr["name"],
                         pr["trading"].get("trades"), pr["trading"].get("expectancy_pct"), pr["trading"].get("profit_factor"),
                         pr["trading"].get("mdd_pct"), (pr["selection"].get("20") or {}).get("excess"))
            log.info("V3 검증 %.0f분", (time.time() - t3) / 60)
        except Exception as e:  # noqa: BLE001
            log.error("V3 검증 실패: %s", e)
        res = BacktesterV2(pit, cfg, feat).run()
        d = res.to_dict()
        pub.publish_backtest(sb, "V2", "매수후보 V2 엔진", d)
        m = d["metrics"]
        log.info("[V2] %s회 승률 %s%% 기대값 %s%% PF %s 총 %s%% MDD %s%% (%.0f분)", m.get("trades"), m.get("win_rate"),
                 m.get("expectancy_pct"), m.get("profit_factor"), m.get("total_return_pct"), m.get("mdd_pct"),
                 (time.time() - t0) / 60)
        pub.process_backtest_requests(sb, pit, cfg, limit=5, features=feat)
        try:                                                   # 목표 도달 검증용: V3 매일 상위 (feat 지우기 전에)
            ent1 = history_entries(pit, cfg, feat, every=1)
        except Exception as e:  # noqa: BLE001
            log.error("V3 매일 선정 실패: %s", e)
            ent1 = None
        del feat, res
        # ---- 관심종목 검증 (VAL): 5개 탭 공통 기준 — 앱 '검증' 화면 ----
        try:
            from stockeye.analysis import validation
            tv = time.time()
            val = validation.run(pit, v3_entries=ent)
            pub.publish_backtest(sb, "VALID", "관심종목 검증", val)
            for st_ in val["strategies"]:
                log.info("[검증] %s: %s", st_["name"], st_["verdict"]["label"])
            log.info("관심종목 검증 %.0f분", (time.time() - tv) / 60)
        except Exception as e:  # noqa: BLE001
            log.error("관심종목 검증 실패: %s", e)
        try:                                                   # 관심종목 적중률 (HIT) — 앱 '검증' 탭 첫 화면
            run_hitrate(sb, pit, cfg, v3_entries=ent1)
        except Exception as e:  # noqa: BLE001
            log.error("적중률 실패: %s", e)
        pub.publish_status(sb, "backtest", {"done": ["V2", "VALID", "HIT"], "minutes": round((time.time() - t0) / 60, 1)})
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
