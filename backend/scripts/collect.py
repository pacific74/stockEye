"""데이터 수집.

  python -m scripts.collect --start 2021-01-01            # 최초 (5년치, 수 시간 걸릴 수 있음)
  python -m scripts.collect                               # 매일 장 마감 후 (18:00 이후 권장)
  python -m scripts.collect --synthetic                   # 인터넷 없이 가짜 데이터로 시험
"""
from __future__ import annotations

import argparse
import logging

import pandas as pd

from stockeye.config import load_config, data_dir
from stockeye.data.store import DataStore
from stockeye.data.collector import collect_range, collect_disclosures, load_synthetic


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start")
    ap.add_argument("--end", default=pd.Timestamp.today().strftime("%Y-%m-%d"))
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--n", type=int, default=400, help="합성 데이터 종목 수")
    ap.add_argument("--no-flows", action="store_true")
    ap.add_argument("--dart-only", action="store_true", help="공시만 수집 (--start 필요)")
    ap.add_argument("--sectors-only", action="store_true", help="업종 분류만 수집 (다른 수집과 동시에 실행해도 안전)")
    ap.add_argument("--kis-program", action="store_true", help="KIS 종목별 프로그램매매 수집 (1차 필터 통과 종목)")
    args = ap.parse_args()
    # pykrx 내부 로그(잘못된 포맷으로 에러 덤프를 찍음)는 숨기고 StockEye 로그만 INFO 로 표시
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("stockeye").setLevel(logging.INFO)

    cfg = load_config()
    store = DataStore(data_dir(cfg))
    if args.synthetic:
        lst = store.load("listing")
        if not lst.empty and not lst["name"].astype(str).str.startswith("합성기업").all():
            raise SystemExit("⚠ 실제 수집 데이터가 이미 있습니다. 합성 데이터로 덮어쓰지 않고 중단합니다.\n"
                             "  (정말 지우려면 data 폴더를 다른 이름으로 옮긴 뒤 다시 실행)")
        load_synthetic(store, n_stocks=args.n)
        print(f"합성 데이터 저장 완료 → {store.root}")
        return

    import os
    if not (os.getenv("KRX_ID") and os.getenv("KRX_PW")):
        print("⚠ KRX_ID / KRX_PW 환경변수가 없습니다. 최신 pykrx 는 data.krx.co.kr 로그인이 필요합니다.\n"
              "  setx KRX_ID 아이디  &  setx KRX_PW 비밀번호  (새 터미널에서 적용)")
    from stockeye.data.sources.dart_source import DartSource
    if args.dart_only:
        if not args.start:
            raise SystemExit("--dart-only 는 --start 가 필요합니다 (예: --start 2021-01-01)")
        collect_disclosures(store, DartSource(), args.start, args.end)
        print(f"공시 수집 완료 → {store.root}")
        return
    from stockeye.data.sources.pykrx_source import PykrxSource
    if args.sectors_only:
        from stockeye.data.collector import collect_sectors
        src = PykrxSource()
        for back in range(8):   # 휴장일이면 하루씩 앞으로 (ohlcv 파일은 건드리지 않음)
            d = pd.Timestamp(args.end) - pd.Timedelta(days=back)
            if d.weekday() < 5 and not src.sectors(d).empty:
                break
        collect_sectors(store, src, d)
        print(f"업종 분류 저장 완료 → {store.root}")
        return
    if args.kis_program:
        from stockeye.data.sources.kis_source import collect_program
        collect_program(store, cfg)
        print(f"프로그램매매 저장 완료 → {store.root}")
        return
    last = store.last_date("ohlcv")
    # 마지막 저장일부터 다시 (장중에 받은 미완성 하루치를 완성본으로 덮어쓰기 위해)
    start = args.start or (last.strftime("%Y-%m-%d") if last is not None else None)
    if start is None:
        raise SystemExit("처음 수집이면 --start 를 지정하세요 (예: --start 2021-01-01)")
    collect_range(store, PykrxSource(), start, args.end, with_flows=not args.no_flows)
    collect_disclosures(store, DartSource(), start, args.end)
    print(f"수집 완료 → {store.root}")


if __name__ == "__main__":
    main()
