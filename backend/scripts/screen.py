"""오늘의 매수 후보 출력 + JSON 저장.

  python -m scripts.screen                      # 데이터 마지막 날 18:00 기준
  python -m scripts.screen --as-of "2025-10-10 18:00"
"""
from __future__ import annotations

import argparse
import json

import pandas as pd

from stockeye.config import load_config, data_dir
from stockeye.data.store import DataStore
from stockeye.data.pit import PointInTimeData
from stockeye.engine.screener import screen, default_as_of
from stockeye.engine.scoring import LABELS


def stars(n):
    return "★" * n + "☆" * (5 - n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--detail", type=int, default=1, help="상세 출력할 상위 종목 수")
    args = ap.parse_args()

    cfg = load_config()
    store = DataStore(data_dir(cfg))
    pit = PointInTimeData.from_store(store)
    as_of = pd.Timestamp(args.as_of) if args.as_of else default_as_of(pit.trading_dates()[-1])
    res = screen(pit.view(as_of), cfg)

    print(f"\n기준 시각: {as_of}   (이 시각 이전 공개 데이터만 사용)")
    print("  →  ".join(f"{k} {v:,}" for k, v in res.funnel))
    print("\n오늘의 매수 후보")
    for c in res.candidates[: args.top]:
        print(f"{c.rank:>2}위  {c.name:<12} {c.score:5.1f}점  {stars(c.stars)}  [{c.plan['verdict']}]")

    for c in res.candidates[: args.detail]:
        p = c.plan
        print(f"\n━━━━━━━━ {c.name} ({c.code}) ━━━━━━━━")
        print(f"현재가          {p['price']:>10,}원")
        print(f"매수 적정구간   {p['entry_low']:>10,} ~ {p['entry_high']:,}원")
        print(f"1차 목표가      {p['target1']:>10,}원   (+{p['target1_pct']}%)")
        print(f"2차 목표가      {p['target2']:>10,}원   (+{p['target2_pct']}%)")
        print(f"손절가격        {p['stop']:>10,}원   ({p['loss_pct']}%)")
        print(f"위험/보상       1 : {p['rr1']}")
        print(f"판정            {p['verdict']} — {p['verdict_reason']}")
        print("점수 구성       " + ", ".join(f"{LABELS[k]} {v}/{c.max_parts[k]}" for k, v in c.parts.items()))
        if c.missing:
            print("데이터 없음     " + ", ".join(LABELS[k] for k in c.missing) + " (나머지로 100점 환산)")
        print("\n매수 근거")
        for r in c.reasons:
            print(f"  ✓ {r}")
        if c.warnings:
            print("주의사항")
            for w in c.warnings:
                print(f"  ⚠ {w}")

    out = data_dir(cfg) / "screen_latest.json"
    out.write_text(json.dumps(res.to_dict(), ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
