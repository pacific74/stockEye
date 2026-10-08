"""장중 재분석 (평일 11:00 · 14:00, GitHub Actions) — 지금 가격으로 '오늘 봉'을 만들어 V2 를 다시 계산·발행.

  python -m scripts.intraday            # 지금 시세로 재분석 → 앱의 후보·점수·매수 신호 갱신
  python -m scripts.intraday --dry-run  # 발행하지 않고 결과만 출력

- 원본 데이터(Storage)는 바꾸지 않는다. 진짜 '오늘 데이터'는 저녁 18:40 배치가 KRX 에서 받아 덮어쓴다.
- 오늘 봉은 진행 중이라 확정값이 아니다: 수급(외국인·기관)은 어제까지, 거래량은 지금까지 누적.
- 발행된 리포트에는 market.intraday = "11:00" 표시 → 앱이 '오늘 11:00 장중 분석' 으로 보여주고,
  저녁 배치는 이 표시가 있으면 '아직 발행 안 됨' 으로 보고 정상 분석한다.
- 휴장일·장 시작 전·시세를 대부분 못 받으면 아무것도 하지 않는다.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

import pandas as pd

from stockeye.config import load_config, data_dir
from stockeye.data.pit import PointInTimeData
from stockeye.data.store import DataStore

log = logging.getLogger("stockeye.intraday")


def today_bars(pit: PointInTimeData, today: pd.Timestamp, live: pd.DataFrame) -> pd.DataFrame:
    """네이버 지금 시세 → ohlcv 형식의 오늘 봉"""
    cols = ["code", "open", "high", "low", "close", "volume", "value", "chg_pct"]
    b = live[cols].copy()
    for c in ("open", "high", "low", "close", "volume"):
        b[c] = b[c].round().astype("int64")
    b["value"] = b["value"].astype("int64")
    b["chg_pct"] = b["chg_pct"].astype("float32")
    b["date"] = today
    return b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--min-coverage", type=float, default=0.8, help="이 비율 미만으로 시세를 받으면 중단")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    logging.getLogger("stockeye").setLevel(logging.INFO)
    t0 = time.time()
    now = pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None)
    today = now.normalize()
    hm = now.strftime("%H:%M")
    if now.weekday() >= 5:
        print("주말 → 생략"); return
    if not ("09:10" <= hm <= "15:40"):
        print(f"장중이 아님 ({hm}) → 생략"); return

    from stockeye.data.sources import naver_live
    idx = naver_live.indices()
    k = idx[idx["code"] == "KOSPI"] if not idx.empty else idx
    if k.empty:
        print("지수 시세를 받지 못함 → 생략"); return
    traded = k.iloc[0]["traded_at"]
    if traded is None or pd.Timestamp(traded).normalize() != today:
        print(f"오늘 거래 없음 (휴장일, 마지막 체결 {traded}) → 생략"); return

    cfg = load_config()
    store = DataStore(data_dir(cfg))
    from stockeye.cloud.client import Supabase
    from stockeye.cloud.sync import DataSync
    sb = Supabase()
    DataSync(store, sb).pull()
    pit = PointInTimeData.from_store(store)
    last = pit.ohlcv["date"].max()
    if last >= today:
        print("이미 오늘 확정 데이터가 있음 → 장중 재분석 불필요"); return
    active = pit.ohlcv.loc[pit.ohlcv["date"] == last, "code"].unique().tolist()
    live = naver_live.stocks(active)
    cov = len(live) / max(len(active), 1)
    log.info("지금 시세 %d / %d종목 (%.0f%%)", len(live), len(active), cov * 100)
    if cov < args.min_coverage:
        print(f"시세를 {cov:.0%} 만 받음 (기준 {args.min_coverage:.0%}) → 재분석 생략"); return

    # 오늘 봉(진행 중) + 지수 오늘 값 붙이기 (메모리에서만)
    bars = today_bars(pit, today, live)
    pit.ohlcv = pd.concat([pit.ohlcv, bars[pit.ohlcv.columns.intersection(bars.columns)]], ignore_index=True)
    ix = idx[["code", "close"]].copy()
    ix["date"] = today
    pit.index = pd.concat([pit.index, ix[pit.index.columns.intersection(ix.columns)]], ignore_index=True)

    from stockeye.report import build_report_full
    from stockeye.details import build_details
    from stockeye.cloud import publish as pub
    as_of = today + pd.Timedelta(hours=18)          # 진행 중인 오늘 봉을 '알 수 있는' 것으로 취급
    report, res, view = build_report_full(pit, cfg, as_of, with_ai=False)
    report["market"]["intraday"] = hm
    if report.get("v3"):                      # 장중엔 선정 기록 없이 읽기만 (기록은 저녁 배치)
        from stockeye.engine.v3_report import attach_portfolio
        try:
            attach_portfolio(report, pit, DataSync(store, sb), record=False, eligible=getattr(res, "v3_eligible", None))
        except Exception as e:  # noqa: BLE001
            log.warning("V3 모의 보유 계산 실패: %s", e)
    report["intraday"] = {"time": hm, "coverage": round(cov, 3)}
    v2 = report.get("v2", {})
    print(f"장중 재분석 {report['date']} {hm}: 시장 {v2.get('market')} / {v2.get('counts')}")
    if args.dry_run:
        return
    pub.publish_report(sb, report)
    rows = build_details(pit, cfg, report, res, view, similar=False)
    for r in rows:                     # 비슷한 패턴은 저녁에 만든 것을 그대로 둠 (칸을 보내지 않으면 안 바뀜)
        r.pop("similar_patterns", None)
    pub.publish_details(sb, rows, report["date"])
    print(f"발행 완료 ({(time.time() - t0) / 60:.1f}분)")


if __name__ == "__main__":
    main()
