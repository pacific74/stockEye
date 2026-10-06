"""백테스트 실행.

  python -m scripts.backtest strategies/breakout_foreign.yaml
  python -m scripts.backtest --engine --min-score 75        # 실전 종목 선정 엔진 그대로 검증
"""
from __future__ import annotations

import argparse
import json

import yaml

from stockeye.config import load_config, data_dir
from stockeye.data.store import DataStore
from stockeye.data.pit import PointInTimeData
from stockeye.backtest.engine import Backtester
from stockeye.backtest.strategy import RuleStrategy, ScreenerStrategy, NamedStrategy
from stockeye.engine.strategies import STRATEGIES
from stockeye.backtest.lookahead import audit
from stockeye.backtest.costs import CostModel


def fmt(m: dict) -> str:
    def g(k, suf="", f="{:,}"):
        v = m.get(k)
        return "-" if v is None else f.format(v) + suf
    return "\n".join([
        f"총 매매          {g('trades', '회')}",
        f"승률             {g('win_rate', '%')}",
        f"평균 수익        +{g('avg_win_pct', '%')}",
        f"평균 손실        {g('avg_loss_pct', '%')}",
        f"1회 기대값       {g('expectancy_pct', '%')}",
        f"Profit Factor    {g('profit_factor')}",
        f"최대 연속손실    {g('max_consec_losses', '회')}",
        f"최대 낙폭(MDD)   {g('mdd_pct', '%')}",
        f"최종 수익률      {g('total_return_pct', '%')}   (연 {g('cagr_pct', '%')})",
        f"샤프 지수        {g('sharpe')}",
        f"벤치마크(KOSPI)  {g('benchmark_return_pct', '%')}",
    ])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("strategy_file", nargs="?")
    ap.add_argument("--engine", action="store_true", help="StockEye 종목 선정 엔진으로 백테스트")
    ap.add_argument("--strategy", help="전략 A~E 하나")
    ap.add_argument("--all-strategies", action="store_true", help="전략 A~E 모두 (전략별 결과 저장)")
    ap.add_argument("--min-score", type=float, default=75)
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--no-audit", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    pit = PointInTimeData.from_store(DataStore(data_dir(cfg)))
    print("지표 계산 중... (전 종목 × 전 기간, 몇 분 걸릴 수 있음)")
    bt = Backtester(pit, cfg)

    jobs = []
    if args.all_strategies:
        jobs = [(k, NamedStrategy(k, cfg)) for k in STRATEGIES]
    elif args.strategy:
        jobs = [(args.strategy, NamedStrategy(args.strategy, cfg))]
    elif args.engine:
        jobs = [(None, ScreenerStrategy(cfg, args.min_score))]
    else:
        spec = yaml.safe_load(open(args.strategy_file or "strategies/breakout_foreign.yaml", encoding="utf-8"))
        args.start = args.start or spec.get("start")
        args.end = args.end or spec.get("end")
        jobs = [(None, RuleStrategy(spec["rules"], cfg, spec.get("rank_by", "score")))]

    summary = []
    for key, strat in jobs:
        res = bt.run(strat, args.start, args.end)
        print(f"\n{'=' * 60}\n전략: {res.strategy}")
        print(f"기간: {res.start} ~ {res.end}")
        print(f"비용: 왕복 약 {CostModel.from_cfg(cfg).round_trip_pct():.2f}% (수수료+세금+슬리피지) 반영\n")
        print(fmt(res.metrics))
        print("\n[표본 내 / 표본 외 비교]  ← 표본 외 성과가 크게 나쁘면 과최적화 의심")
        for lab, mm in (("표본 내", res.metrics_is), ("표본 외", res.metrics_oos)):
            print(f"  {lab} {mm.get('period')}: 수익 {mm.get('total_return_pct')}%, "
                  f"승률 {mm.get('win_rate')}%, 기대값 {mm.get('expectancy_pct')}%")
        print("\n[연도별]")
        for y in res.yearly:
            print(f"  {y['year']}: {y['return_pct']:+.1f}%  매매 {y['trades']}회  승률 {y['win_rate']}%  MDD {y['mdd_pct']}%")
        for w in res.warnings:
            print(f"⚠ {w}")
        if not args.no_audit:
            print("\n미래참조 감사 실행 중...")
            rep = audit(pit, bt.features, strat, res.trades)
            res.audit = rep.to_dict()
            print(rep)
            if not rep.passed:
                print("\n❌ 감사 실패: 이 백테스트 결과는 신뢰할 수 없습니다.")
        d = res.to_dict()
        out = data_dir(cfg) / "backtest_latest.json"
        out.write_text(json.dumps(d, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        if key:
            (data_dir(cfg) / "backtests").mkdir(exist_ok=True)
            (data_dir(cfg) / "backtests" / f"{key}.json").write_text(
                json.dumps(d, ensure_ascii=False, default=str), encoding="utf-8")
        summary.append((key or "-", res))

    if len(summary) > 1:
        print(f"\n{'=' * 60}\n전략별 비교 (비용 반영)")
        print(f"{'전략':<16}{'매매':>6}{'승률':>8}{'기대값':>8}{'수익률':>9}{'MDD':>8}{'표본외':>9}")
        for key, r in summary:
            m, o = r.metrics, r.metrics_oos
            nm = STRATEGIES[key].short if key in STRATEGIES else key
            print(f"{key}.{nm:<13}{m['trades']:>6}{(m['win_rate'] or 0):>7}%{(m['expectancy_pct'] or 0):>7}%"
                  f"{m.get('total_return_pct', 0):>8}%{m.get('mdd_pct', 0):>7}%{o.get('total_return_pct', 0):>8}%")


if __name__ == "__main__":
    main()
