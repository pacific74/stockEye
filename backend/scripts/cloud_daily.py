"""클라우드 일일 배치 (GitHub Actions / 클라우드 VM 에서 평일 18:30 자동 실행).

  ① Storage 에서 원본 데이터 받기  ② 오늘치 수집(KRX·DART·KIS 프로그램매매)  ③ Storage 에 올리기
  ④ 리포트(시장·업종·TOP10·전략 A~E)  ⑤ 전 종목 상세  ⑥ 매매일지 분석·보유종목 점검
  ⑦ 앱에서 요청한 백테스트  ⑧ 휴대폰 알림

  python -m scripts.cloud_daily
  python -m scripts.cloud_daily --skip-collect     # 수집 없이 분석·발행만 (시험용)

필요한 환경변수: SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPABASE_USER_ID, KRX_ID, KRX_PW, DART_API_KEY
선택: KIS_APP_KEY/KIS_APP_SECRET(프로그램매매), ANTHROPIC_API_KEY(AI 설명), NTFY_TOPIC 또는 TELEGRAM_*
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import time
import traceback

import pandas as pd

from stockeye.config import load_config, data_dir
from stockeye.data.store import DataStore
from stockeye.data.pit import PointInTimeData
from stockeye.cloud.client import Supabase
from stockeye.cloud.sync import DataSync
from stockeye.cloud import publish as pub

log = logging.getLogger("stockeye.cloud_daily")
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def step(name, fn, errors: list, required: bool = False):
    t = time.time()
    log.info("▶ %s", name)
    try:
        r = fn()
        log.info("✔ %s (%.0f초)", name, time.time() - t)
        return r
    except Exception as e:  # noqa: BLE001
        log.error("✖ %s 실패: %s\n%s", name, e, traceback.format_exc(limit=3))
        errors.append(f"{name}: {e}")
        if required:
            raise
        return None


def collect(store: DataStore, cfg: dict, errors: list) -> None:
    from stockeye.data.collector import collect_range, collect_disclosures
    from stockeye.data.sources.pykrx_source import PykrxSource
    today = pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d")
    last = store.last_date("ohlcv")
    if last is None:
        raise RuntimeError("원본 데이터가 없습니다. PC 에서 먼저 python -m scripts.cloud_push 로 올려 주세요.")
    start = last.strftime("%Y-%m-%d")
    before = store.last_date("ohlcv")
    step("KRX 시세·수급 수집", lambda: collect_range(store, PykrxSource(), start, today), errors, required=True)
    after = store.last_date("ohlcv")
    log.info("시세 마지막 날짜: %s → %s", before.date(), after.date())
    if os.getenv("DART_API_KEY"):
        from stockeye.data.sources.dart_source import DartSource
        step("DART 공시 수집", lambda: collect_disclosures(store, DartSource(), start, today), errors)
    if os.getenv("KIS_APP_KEY") and os.getenv("KIS_APP_SECRET"):
        from stockeye.data.sources.kis_source import collect_program
        step("KIS 프로그램매매 수집", lambda: collect_program(store, cfg), errors)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-collect", action="store_true")
    ap.add_argument("--no-push", action="store_true", help="수집한 원본 데이터를 Storage 에 올리지 않음")
    ap.add_argument("--no-similar", action="store_true", help="비슷한 패턴 계산 생략")
    ap.add_argument("--no-requests", action="store_true", help="앱의 백테스트 요청 처리 생략")
    ap.add_argument("--as-of")
    ap.add_argument("--force", action="store_true", help="이미 발행한 날짜라도 다시 분석·발행")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    logging.getLogger("stockeye").setLevel(logging.INFO)

    t0 = time.time()
    cfg = load_config()
    store = DataStore(data_dir(cfg))
    sb = Supabase()
    sync = DataSync(store, sb)
    errors: list[str] = []

    step("Storage → 원본 데이터 받기", sync.pull, errors, required=True)
    if not args.skip_collect:
        step("오늘 데이터 수집", lambda: collect(store, cfg, errors), errors, required=True)
        if not args.no_push:
            step("원본 데이터 → Storage 올리기", sync.push, errors)
        last = store.last_date("ohlcv").strftime("%Y-%m-%d")
        done = sb.select("daily_reports", {"select": "date", "date": f"eq.{last}"})
        if done and not args.as_of and not args.force:
            log.info("새 거래일 데이터가 없습니다 (휴장일이거나 이미 발행됨: %s) → 분석 생략", last)
            if not args.no_requests:
                step("앱 백테스트 요청 처리",
                     lambda: pub.process_backtest_requests(sb, PointInTimeData.from_store(store), cfg, limit=2), errors)
            return

    from stockeye.report import build_report_full, save_report
    from stockeye.details import build_details
    pit = PointInTimeData.from_store(store)
    report, res, view = step("리포트 만들기", lambda: build_report_full(pit, cfg, args.as_of), errors, required=True)
    save_report(report, cfg)
    step("리포트 → Storage", lambda: (sync.put_json("reports/latest.json", report),
                                       sync.put_json(f"reports/{report['date']}.json", report)), errors)
    step("리포트 발행", lambda: pub.publish_report(sb, report), errors, required=True)
    rows = step("종목 상세 만들기", lambda: build_details(pit, cfg, report, res, view, similar=not args.no_similar),
                errors)
    if rows:
        step("종목 상세 발행", lambda: pub.publish_details(sb, rows, report["date"]), errors)

    # 매매일지: 앱을 쓰는 모든 사용자 각각 (본인 데이터만 본인에게 보임)
    from stockeye.cloud.journal import CloudJournal
    uids = {r["user_id"] for r in sb.select("positions", {"select": "user_id", "limit": "100000"})}
    owner = (os.getenv("SUPABASE_USER_ID") or "").strip()
    if owner and not UUID_RE.match(owner):
        errors.append("SUPABASE_USER_ID 가 User UID 형식이 아닙니다 (이메일이 아니라 "
                      "Supabase → Authentication → Users 에서 복사한 36자리 값을 넣으세요)")
        log.error(errors[-1])
    elif owner:
        uids.add(owner)
    last_bar = pit.ohlcv[pit.ohlcv["date"] == pit.ohlcv["date"].max()].set_index("code")
    for uid in sorted(uids):
        j = CloudJournal(sb, user_id=uid)

        def track(j=j):
            for p in j.positions(status="open"):
                if p["code"] in last_bar.index:
                    r = last_bar.loc[p["code"]]
                    j.track_price(p["id"], float(r["low"]), float(r["high"]))
        step(f"[{uid[:8]}] 보유 포지션 최고/최저가 갱신", track, errors)
        step(f"[{uid[:8]}] 매매 분석·보유종목 점검 발행", lambda j=j: pub.publish_journal(sb, cfg, j, pit, report), errors)
    log.info("매매일지 사용자 %d명 처리", len(uids))

    if not args.no_requests:
        step("앱 백테스트 요청 처리", lambda: pub.process_backtest_requests(sb, pit, cfg, limit=2), errors)

    status = {"date": report["date"], "finished": pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d %H:%M"),
              "minutes": round((time.time() - t0) / 60, 1), "errors": errors,
              "runner": os.getenv("STOCKEYE_RUNNER", "github" if os.getenv("GITHUB_ACTIONS") else "server")}
    pub.publish_status(sb, "batch", status)
    pub.publish_status(sb, "trading", pub.trading_status(cfg))

    from stockeye.trading.notify import Notifier
    n = Notifier()
    top = ", ".join(f"{c['name']}({c['score']:.0f})" for c in report["top10"][:3]) or "후보 없음"
    m = report["market"]
    n.send(f"StockEye {report['date']} 리포트", f"{m.get('mood_icon', '')} {m.get('mood', '')} · TOP3 {top}"
           + (f"\n⚠ 일부 단계 실패 {len(errors)}건" if errors else ""))
    log.info("완료 (%.1f분). 오류 %d건", (time.time() - t0) / 60, len(errors))
    for e in errors:
        log.warning("  - %s", e)


if __name__ == "__main__":
    main()
