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


def collect(store: DataStore, cfg: dict, errors: list, sync=None) -> None:
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
        from scripts.dart_backfill import update_financials_recent
        step("DART 재무 갱신 (최근 정기보고서 낸 회사만)", lambda: update_financials_recent(store, sync), errors)
    if os.getenv("KIS_APP_KEY") and os.getenv("KIS_APP_SECRET"):
        from stockeye.data.sources.kis_source import collect_program
        step("KIS 프로그램매매 수집", lambda: collect_program(store, cfg), errors)


def load_company(sync, date) -> dict | None:
    """기업 개요(업종·주요제품·상장주식수): Storage 캐시가 7일 넘었으면 새로 받아 저장"""
    from stockeye.data.company import fetch_company_meta, is_stale
    meta = None
    try:
        meta = sync.get_json("meta/company.json")
    except Exception as e:  # noqa: BLE001
        log.warning("기업 개요 캐시 읽기 실패: %s", e)
    if is_stale(meta):
        fresh = fetch_company_meta(date)
        if fresh["rows"]:
            sync.put_json("meta/company.json", fresh)
            meta = fresh
    return meta


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
    # 주말·공휴일(휴장일)은 아무것도 하지 않음 (수동 실행 --force / --as-of / --skip-collect 는 그대로 진행)
    if not (args.force or args.as_of or args.skip_collect):
        from stockeye.data.sources.naver_live import is_trading_day
        open_today = is_trading_day()
        if open_today is False:
            log.info("오늘은 휴장일(주말·공휴일) → 일일 배치 생략")
            print("오늘은 휴장일(주말·공휴일) → 일일 배치 생략")
            return
        if open_today is None:
            log.warning("휴장일 여부를 확인하지 못해 평소대로 진행 (새 데이터가 없으면 분석은 자동 생략)")
    cfg = load_config()
    store = DataStore(data_dir(cfg))
    sb = Supabase()
    sync = DataSync(store, sb)
    errors: list[str] = []

    step("Storage → 원본 데이터 받기", sync.pull, errors, required=True)
    if not args.skip_collect:
        step("오늘 데이터 수집", lambda: collect(store, cfg, errors, sync), errors, required=True)
        if not args.no_push:
            step("원본 데이터 → Storage 올리기", sync.push, errors)
        last = store.last_date("ohlcv").strftime("%Y-%m-%d")
        done = sb.select("daily_reports", {"select": "date,market", "date": f"eq.{last}"})
        done = [d for d in done if not (d.get("market") or {}).get("intraday")]   # 장중 재분석 결과는 '아직 발행 안 됨'
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
    if report.get("v3"):
        from stockeye.engine.v3_report import attach_portfolio
        step("V3 기준 전략: 선정 기록·모의 보유·매도 예정일",
             lambda: attach_portfolio(report, pit, sync, record=not args.as_of, eligible=getattr(res, "v3_eligible", None)),
             errors)
    # 뉴스 (네이버 API HUB): 탭 상위·보유종목 최근 3일 → 종목 상세 '최근 뉴스' · 악재 경고 · 4개 탭 점수 반영
    from stockeye.analysis.news_flags import annotate as news_annotate
    def _news():
        rows_ = sb.select("positions", {"select": "code,name", "status": "eq.open", "limit": "100000"})
        return news_annotate(report, {r["code"]: r.get("name") or r["code"] for r in rows_})
    step("뉴스 (네이버 API HUB)", _news, errors)
    if report.get("nextday"):
        from stockeye.engine.nextday_report import attach_log
        step("익일 유망주: 후보 기록·어제 후보 결과",
             lambda: attach_log(report, pit, sync, record=not args.as_of), errors)
    save_report(report, cfg)
    step("리포트 → Storage", lambda: (sync.put_json("reports/latest.json", report),
                                       sync.put_json(f"reports/{report['date']}.json", report)), errors)
    step("리포트 발행", lambda: pub.publish_report(sb, report), errors, required=True)
    def _stock_info():                                               # 앱 카드 [시장][업종 · 테마][시총] 한 줄
        from stockeye.analysis.market import stock_info, load_themes
        info = stock_info(pit.listing, getattr(pit, "sectors", None), load_themes(), getattr(pit, "flows", None))
        pub.publish_status(sb, "stock_info", {"date": report["date"], "info": info})
        return len(info)
    step("종목 정보 발행 (시장·업종·테마·시총)", _stock_info, errors)
    if report.get("sector_members"):                                # 앱 업종 상세 '전체 종목' (업종마다 전 종목 등락)
        step("업종 전체 종목 발행", lambda: pub.publish_status(sb, "sector_members", {
            "date": report["date"], **report["sector_members"]}), errors)
    if not args.as_of:                                              # 검증용 추천 기록 (영구 · 같은 날 첫 기록만)
        from stockeye.cloud.recommend import record_daily
        step("추천 기록 (검증용)", lambda: record_daily(sb, report), errors)
    from stockeye.cloud.entry_info import annotate_positions
    step("매매일지: 매수 당시 후보·점수·상태 기록", lambda: annotate_positions(sb, sync), errors)
    company = step("기업 개요 (주 1회 갱신)", lambda: load_company(sync, report["date"]), errors)
    held = step("보유종목 목록 (비슷한 패턴용)", lambda: sorted({r["code"] for r in sb.select(
        "positions", {"select": "code", "status": "eq.open", "limit": "100000"})}), errors) or []
    from stockeye.cloud.patterns import recent_requested, process_pattern_requests
    asked = step("최근 검색 요청 종목 (비슷한 패턴 계속 갱신)", lambda: recent_requested(sb), errors) or []
    rows = step("종목 상세 만들기", lambda: build_details(pit, cfg, report, res, view, similar=not args.no_similar,
                                                         company=company, similar_codes=held + asked), errors)
    if rows:
        step("종목 상세 발행", lambda: pub.publish_details(sb, rows, report["date"]), errors)
    step("검색 종목 패턴 요청 처리", lambda: process_pattern_requests(sb, pit), errors)
    # 당일단타: 오늘 아침 PC 가 남긴 신호 → 오늘 1분봉으로 결과 (1·2차 익절·손절·마감) → 검증 탭에 누적
    if os.getenv("KIS_APP_KEY") and not args.as_of:
        def _daytrade():
            from stockeye.analysis.daytrade_eval import evaluate_day
            from stockeye.data.sources.kis_source import KISClient
            kc = cfg.get("kis", {})
            kis = KISClient(kc.get("env", "prod"), data_dir(cfg) / ".kis_token.json", kc.get("calls_per_sec", 15))
            return evaluate_day(sb, kis, report["date"])
        step("당일단타 결과 매기기", _daytrade, errors)

        # 종가배팅: 지난 거래일 15:20 매수 후보 → 그날 종가 매수 · 오늘 오전(10:30 까지) 매도 결과 → 검증 탭
        def _closingbet():
            from stockeye.analysis.closingbet_eval import evaluate_prev
            from stockeye.data.sources.kis_source import KISClient
            kc = cfg.get("kis", {})
            kis = KISClient(kc.get("env", "prod"), data_dir(cfg) / ".kis_token.json", kc.get("calls_per_sec", 15))
            oh = pit.ohlcv

            def close_of(code, d):
                r = oh[(oh["code"] == code) & (oh["date"] == pd.Timestamp(d))]
                return float(r["close"].iloc[0]) if len(r) else None
            return evaluate_prev(sb, kis, report["date"], close_of)
        step("종가배팅 결과 매기기", _closingbet, errors)

        # 상한가포착: 지난 거래일 '매수 검토' → 그날 조건 무효 여부 · 오늘 시가 절반 · 09:30 청산 결과 + 점수 구간별 유지율
        def _limitcatch():
            from stockeye.analysis.limitcatch_eval import evaluate_prev as lc_prev
            from stockeye.data.sources.kis_source import KISClient
            kc = cfg.get("kis", {})
            kis = KISClient(kc.get("env", "prod"), data_dir(cfg) / ".kis_token.json", kc.get("calls_per_sec", 15))
            oh = pit.ohlcv

            def row_of(code, d):
                r = oh[(oh["code"] == code) & (oh["date"] == pd.Timestamp(d))]
                return r.iloc[0].to_dict() if len(r) else None
            return lc_prev(sb, kis, report["date"], row_of)
        step("상한가포착 결과 매기기", _limitcatch, errors)

        # 당일매매 추적 마무리: PC(실시간)가 꺼졌거나 멈춰 결과가 안 난 고정 종목을 오늘 1분봉으로 마무리 → 관리자 매매일지
        def _intraday_finish():
            from stockeye.trading.intraday_track import finish_day
            from stockeye.data.sources.kis_source import KISClient
            kc = cfg.get("kis", {})
            kis = KISClient(kc.get("env", "prod"), data_dir(cfg) / ".kis_token.json", kc.get("calls_per_sec", 15))
            return finish_day(sb, kis, report["date"])
        step("당일매매 추적 마무리 (PC 꺼짐 대비)", _intraday_finish, errors)

        # 당일매매 시장·업종 기록: 오늘 당일단타 매수→청산 구간의 시장·업종 흐름 누적 → 앱 '검증 > 시장·업종' (시장 필터·진입 시간 조절 근거)
        def _intraday_ctx():
            from stockeye.analysis.intraday_ctx import run as ctx_run
            from stockeye.data.sources.kis_source import KISClient
            kc = cfg.get("kis", {})
            kis = KISClient(kc.get("env", "prod"), data_dir(cfg) / ".kis_token.json", kc.get("calls_per_sec", 15))
            return ctx_run(sb, kis, pit.listing, getattr(pit, "sectors", None), report["date"])
        step("당일매매 시장·업종 기록", _intraday_ctx, errors)

    # 추천주 검증: recommendations 결과 칸 채우기(관심 탭 20거래일 · 장중 탭은 위 실전 기록) + 통계 → 앱 '검증 > 추천주'
    if not args.as_of:
        from stockeye.analysis.rec_eval import run as rec_run
        step("추천주 검증 (결과·통계)", lambda: rec_run(sb, pit.ohlcv, report["date"]), errors)

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
    try:   # 관리자에게: 가입 승인 대기 인원
        pending = sb.count("profiles", {"status": "eq.pending"})
    except Exception:  # noqa: BLE001  (예전 스키마)
        pending = 0
    from stockeye.cloud.digest import build as build_digest
    d_title, d_body = build_digest(report)
    n.send(d_title, d_body
           + (f"\n\n👤 가입 승인 대기 {pending}명 (앱 → 회원 관리)" if pending else "")
           + (f"\n\n⚠ 일부 단계 실패 {len(errors)}건" if errors else ""), markdown=True)
    if owner and UUID_RE.match(owner):        # 관리자 본인 보유종목 점검 (회원과 같은 기준)
        def admin_holdings():
            lines = pub.holding_alerts(sb, owner)
            if lines:
                n.send(f"StockEye 보유종목 점검 ({report['date']})", "\n".join(lines), priority="high",
                       url=os.getenv("WEB_URL") or None)
        step("관리자 보유종목 점검 알림", admin_holdings, errors)
    step("회원별 알림", lambda: pub.notify_members(sb, report, n, skip_topics=[n.ntfy or ""],
                                                app_url=os.getenv("WEB_URL") or None), errors)
    log.info("완료 (%.1f분). 오류 %d건", (time.time() - t0) / 60, len(errors))
    for e in errors:
        log.warning("  - %s", e)


if __name__ == "__main__":
    main()
