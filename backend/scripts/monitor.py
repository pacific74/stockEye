"""장중 실시간 감시 (3~5단계).

  python -m scripts.monitor                       # settings.yaml 의 trading.mode 대로 (기본 alert)
  python -m scripts.monitor --mode paper          # 4단계 모의투자 자동 체결
  python -m scripts.monitor --replay 2026-10-02   # KIS 없이 과거 하루를 재생해서 흐름 시험 (전날 리포트 기준)

필요: KIS_APP_KEY / KIS_APP_SECRET (실시간 시세). 재생 모드는 필요 없음.
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, time as dtime

import pandas as pd

from stockeye.config import load_config, data_dir, deep_merge
from stockeye.data.store import DataStore
from stockeye.data.pit import PointInTimeData, at, DECISION_TIME
from stockeye.report import load_latest, build_report
from stockeye.trading.journal import Journal, make_journal
from stockeye.trading.notify import Notifier
from stockeye.trading.engine import TradingEngine, KISQuotes, ReplayQuotes
from stockeye.trading.brokers import make_broker


def _latest_report(cfg):
    """PC 의 최신 리포트, 클라우드에 더 최신 리포트가 있으면 그것."""
    rep = load_latest(cfg)
    try:
        from stockeye.cloud.client import enabled
        if enabled():
            from stockeye.cloud.sync import DataSync
            cloud = DataSync(DataStore(data_dir(cfg))).get_json("reports/latest.json")
            if cloud and (rep is None or cloud["date"] > rep["date"]):
                return cloud
    except Exception as e:  # noqa: BLE001
        logging.getLogger("stockeye").warning("클라우드 리포트 확인 실패: %s", e)
    return rep


def run_live(cfg, journal, notifier):
    from stockeye.data.sources.kis_source import KISClient
    kc = cfg.get("kis", {})
    quotes = KISQuotes(KISClient(kc.get("env", "prod"), data_dir(cfg) / ".kis_token.json", kc.get("calls_per_sec", 15)))
    report = _latest_report(cfg)
    if not report:
        raise SystemExit("리포트가 없습니다. 먼저 python -m scripts.daily_report (클라우드: scripts.cloud_daily)")
    eng = TradingEngine(cfg, journal, report, notifier, make_broker(cfg), cfg["trading"].get("app_url"))
    tc = cfg["trading"]
    print(f"[{tc['mode']}] 감시 시작 — 후보 {len(eng.watch)}종목 + 보유 {len(journal.positions(status='open'))}종목, "
          f"리포트 {report['date']} 기준, 알림: {', '.join(notifier.channels)}")
    notifier.send("StockEye 감시 시작", f"모드 {tc['mode']} · 감시 {len(eng.codes_to_watch())}종목")
    members = None
    try:   # 회원 장중 알림 (클라우드일 때)
        from stockeye.cloud.client import enabled, Supabase
        if enabled():
            from stockeye.trading.member_alerts import MemberAlerts
            import os
            members = MemberAlerts(Supabase(), notifier, os.getenv("SUPABASE_USER_ID"),
                                   app_url=os.getenv("WEB_URL") or None)
            members.refresh(force=True)
            print(f"회원 장중 알림: {len(members.members)}명 · 보유 {len(members.positions)}건 감시")
    except Exception as e:  # noqa: BLE001
        logging.getLogger("stockeye").warning("회원 알림 준비 실패: %s", e)
        members = None
    checked_open = False
    while True:
        now = datetime.now()
        if now.weekday() >= 5 or now.time() > dtime(15, 30):
            print("장 마감 — 종료")
            break
        if now.time() < dtime(9, 1):
            time.sleep(30)
            continue
        if not checked_open:
            checked_open = True
            try:   # 휴장일 확인: 대표 종목 거래량이 0 이면 오늘은 장이 열리지 않은 날
                if quotes.c.price("005930")["volume"] == 0:
                    print("오늘은 휴장일로 보입니다 (거래량 0) — 종료")
                    break
            except Exception as e:  # noqa: BLE001
                logging.getLogger("stockeye").warning("휴장일 확인 실패: %s", e)
        extra = []
        if members is not None:
            members.refresh()
            extra = members.codes()
        qs = quotes.get(sorted(set(eng.codes_to_watch()) | set(extra)))
        evs = eng.tick(qs, now)
        for e in evs:
            logging.getLogger("stockeye").info("%s %s %s", e["type"], e["name"], e.get("reason", ""))
            if members is not None and e["type"] == "entry":
                members.broadcast_entry(e, now)
        if members is not None:
            members.check(qs, now)
        # 앱(휴대폰)에서 승인한 주문 처리 (클라우드 매매일지일 때)
        for r in eng.process_app_approvals(quotes.get):
            logging.getLogger("stockeye").info("앱 승인 주문 %s → %s", r["id"], r.get("message") or r.get("ok"))
        time.sleep(tc.get("poll_seconds", 30))


def run_replay(cfg, journal, notifier, date: str):
    pit = PointInTimeData.from_store(DataStore(data_dir(cfg)))
    dates = pit.trading_dates()
    d = pd.Timestamp(date).normalize()
    if d not in dates:
        raise SystemExit(f"{d.date()} 데이터 없음")
    prev = dates[dates.get_loc(d) - 1]
    print(f"{prev.date()} 18:00 기준 리포트로 {d.date()} 장중 재생 (AI 설명 생략)")
    report = build_report(pit, cfg, at(prev, DECISION_TIME), with_ai=False)
    eng = TradingEngine(cfg, journal, report, notifier, make_broker(cfg))
    rq = ReplayQuotes(pit.ohlcv, d)
    print(f"감시 후보 {len(eng.watch)}종목: {', '.join(c['name'] for c in list(eng.watch.values())[:10])}")
    while True:
        evs = eng.tick(rq.get(eng.codes_to_watch()), rq.now())
        for e in evs:
            print(f"  [{rq.now():%H:%M}] {e['type']:<5} {e['name']} {e['price']:,.0f}원 {e.get('reason', '')}")
        if not rq.advance():
            break
    print(f"\n열린 포지션 {len(journal.positions(status='open'))}개, 완료 {len(journal.positions(status='closed'))}개")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["alert", "paper", "semi_auto"])
    ap.add_argument("--replay", help="YYYY-MM-DD 하루 재생 (KIS 불필요)")
    ap.add_argument("--journal", help="매매일지 DB 경로 (기본 data/journal.db, 재생은 data/journal_replay.db)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("stockeye").setLevel(logging.INFO)
    cfg = load_config()
    if args.mode:
        cfg = deep_merge(cfg, {"trading": {"mode": args.mode}})
    if args.replay and cfg["trading"]["mode"] == "semi_auto":
        cfg = deep_merge(cfg, {"trading": {"broker": "paper"}})   # 재생에서는 절대 실제 주문하지 않음
    if args.replay or args.journal:   # 재생은 항상 PC 의 별도 일지 (클라우드 일지를 더럽히지 않음)
        journal = Journal(args.journal or data_dir(cfg) / "journal_replay.db")
    else:
        journal = make_journal(cfg)   # SUPABASE_* 가 있으면 클라우드 일지 (앱과 공유)
        print(f"매매일지: {journal.path}")
        try:
            from stockeye.cloud.client import enabled
            if enabled():
                from stockeye.cloud.client import Supabase
                from stockeye.cloud.publish import publish_status, trading_status
                publish_status(Supabase(), "trading", {**trading_status(cfg), "monitor": "running"})
        except Exception as e:  # noqa: BLE001
            logging.getLogger("stockeye").warning("매매 상태 발행 실패: %s", e)
    notifier = Notifier()
    if args.replay:   # 재생은 휴대폰으로 보내지 않고 화면에만
        notifier.tg_token = notifier.ntfy = None
        run_replay(cfg, journal, notifier, args.replay)
    else:
        run_live(cfg, journal, notifier)


if __name__ == "__main__":
    main()
