"""매일 장 마감 후: 오늘의 시장 → 업종 강도 → TOP10 → 전략별 후보 → AI 설명 → 저장(+Supabase).

  python -m scripts.daily_report
  python -m scripts.daily_report --no-ai
"""
from __future__ import annotations

import argparse
import logging

from stockeye.config import load_config, data_dir
from stockeye.data.store import DataStore
from stockeye.data.pit import PointInTimeData
from stockeye.report import build_report_full, save_report
from stockeye.trading.journal import make_journal


def stars(n):
    return "★" * n + "☆" * (5 - n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of")
    ap.add_argument("--no-ai", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("stockeye").setLevel(logging.INFO)

    cfg = load_config()
    pit = PointInTimeData.from_store(DataStore(data_dir(cfg)))
    rep, res, view = build_report_full(pit, cfg, args.as_of, with_ai=not args.no_ai)
    path = save_report(rep, cfg)

    m = rep["market"]
    line = "━" * 30
    print(f"\n{line}\n{'오늘의 시장':^26}\n{line}")
    for i in m["indices"]:
        print(f"{i['code']:<8} {i['change_pct']:+.2f}%")
    print(f"시장 분위기   {m['mood_icon']} {m['mood']}  (상승 {m['advancers']} / 하락 {m['decliners']})")
    print("\n돈이 몰리는 업종/테마")
    for k, g in enumerate(rep["sectors"][:6], 1):
        print(f" {k}. {g['group']:<10} {g['score']:>3}  {g['arrows']:<5} 오늘 {g['ret1_pct']:+.1f}%")
        for t in g["top"][:3]:
            sc = f"{t['score']:.0f}점" if t["score"] is not None else "-"
            print(f"     ├ {t['name']:<12} {sc}")
    print(f"\n{line}\n{'오늘의 TOP 10':^26}\n{line}")
    for c in rep["top10"]:
        print(f"{c['rank']:>2}  {c['name']:<12} {c['score']:5.1f} {stars(c['stars'])}  [{c['plan']['verdict']}]")
    for k, v in rep["strategies"].items():
        top = ", ".join(f"{c['name']}({c['plan']['verdict']})" for c in v["candidates"][:3]) or "-"
        print(f"[{v['short']}] {len(v['candidates'])}종목: {top}")
    if rep["top10"]:
        c = rep["top10"][0]
        e = rep["explanations"].get(c["code"])
        if e:
            print(f"\n💬 {c['name']} ({'AI' if e['source'] == 'ai' else '규칙 기반'} 설명)\n{e['text']}")
    if rep.get("unmatched_theme_names"):
        print(f"\n⚠ themes.yaml 에서 찾지 못한 종목명: {', '.join(rep['unmatched_theme_names'][:10])}")
    # 보유 포지션 최고/최저가 갱신 (매매일지의 MAE/MFE) + 상태 출력
    j = make_journal(cfg)
    opens = j.positions(status="open")
    if opens:
        last = pit.ohlcv[pit.ohlcv["date"] == pit.ohlcv["date"].max()].set_index("code")
        print(f"\n보유 포지션 {len(opens)}개")
        for p in opens:
            if p["code"] in last.index:
                r = last.loc[p["code"]]
                j.track_price(p["id"], float(r["low"]), float(r["high"]))
                ret = (float(r["close"]) / p["entry_price"] - 1) * 100
                flag = " ⚠ 손절가 이탈" if p["stop"] and float(r["low"]) <= p["stop"] else (
                    " 🎯 목표 도달" if p["target1"] and float(r["high"]) >= p["target1"] else "")
                print(f"  [{p['mode']}] {p['name']:<12} {ret:+.1f}%{flag}")
    print(f"\n저장: {path}")
    from stockeye.cloud.client import enabled
    if enabled():   # PC 에서 돌려도 SUPABASE_* 가 있으면 앱(클라우드)에 바로 발행
        from stockeye.cloud.client import Supabase
        from stockeye.cloud import publish as pub
        from stockeye.details import build_details
        sbc = Supabase()
        pub.publish_report(sbc, rep)
        company = None
        try:
            from stockeye.cloud.sync import DataSync
            from stockeye.data.store import DataStore
            from stockeye.config import data_dir
            from scripts.cloud_daily import load_company
            company = load_company(DataSync(DataStore(data_dir(cfg)), sbc), rep["date"])
        except Exception as e:  # noqa: BLE001  (기업 개요는 참고용)
            print(f"기업 개요 생략: {e}")
        pub.publish_details(sbc, build_details(pit, cfg, rep, res, view, company=company), rep["date"])
        if hasattr(j, "uid"):
            pub.publish_journal(sbc, cfg, j, pit, rep)
        pub.publish_status(sbc, "trading", pub.trading_status(cfg))
        print("Supabase 발행 완료 (리포트·종목 상세·매매 분석)")


if __name__ == "__main__":
    main()
