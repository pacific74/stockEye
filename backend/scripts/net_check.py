"""이 컴퓨터(또는 GitHub Actions 서버)에서 데이터 소스에 접속되는지 점검.

  python -m scripts.net_check

GitHub Actions 는 미국 서버라서 KRX·KIS 가 해외 접속을 막으면 실패할 수 있다.
실패하면 같은 코드를 서울 리전 클라우드 VM 에서 돌리면 된다 (deploy/vm/README.md).
"""
from __future__ import annotations

import logging
import os
import sys
import time
import traceback

import pandas as pd


def check(name, fn, results):
    t = time.time()
    try:
        msg = fn()
        results.append((name, "OK", f"{msg} ({time.time() - t:.1f}초)"))
    except Exception as e:  # noqa: BLE001
        results.append((name, "FAIL", f"{type(e).__name__}: {str(e)[:200]}"))
        traceback.print_exc(limit=2)


def last_weekday():
    d = pd.Timestamp.now(tz="Asia/Seoul").normalize().tz_localize(None) - pd.Timedelta(days=1)
    while d.weekday() >= 5:
        d -= pd.Timedelta(days=1)
    return d


def main():
    logging.basicConfig(level=logging.WARNING, stream=sys.stdout)
    res = []
    d = last_weekday()

    def ip():
        import requests
        j = requests.get("https://ipinfo.io/json", timeout=10).json()
        return f"{j.get('ip')} · {j.get('country')} {j.get('city')}"
    check("내 공인 IP", ip, res)

    if os.getenv("KRX_ID") and os.getenv("KRX_PW"):
        def krx():
            from stockeye.data.sources.pykrx_source import PykrxSource
            src = PykrxSource()
            days = src.trading_days((d - pd.Timedelta(days=10)).strftime("%Y-%m-%d"), d.strftime("%Y-%m-%d"))
            df = src.ohlcv_day(days[-1])
            if df.empty:
                raise RuntimeError("빈 결과 (로그인/차단 확인)")
            fl = src.flows_day(days[-1])
            return f"{days[-1].date()} 시세 {len(df)}종목 · 수급 {len(fl)}행"
        check("KRX (pykrx)", krx, res)
    else:
        res.append(("KRX (pykrx)", "SKIP", "KRX_ID / KRX_PW 없음"))

    if os.getenv("DART_API_KEY"):
        def dart():
            from stockeye.data.sources.dart_source import DartSource
            df = DartSource().disclosures(d.strftime("%Y-%m-%d"), d.strftime("%Y-%m-%d"))
            return f"{d.date()} 공시 {len(df)}건"
        check("DART", dart, res)
    else:
        res.append(("DART", "SKIP", "DART_API_KEY 없음"))

    if os.getenv("KIS_APP_KEY") and os.getenv("KIS_APP_SECRET"):
        def kis():
            from stockeye.data.sources.kis_source import KISClient
            import tempfile
            from pathlib import Path
            c = KISClient("prod", Path(tempfile.gettempdir()) / ".kis_token_check.json")
            p = c.price("005930")
            return f"삼성전자 {p['price']:,.0f}원"
        check("KIS Open API", kis, res)
    else:
        res.append(("KIS Open API", "SKIP", "KIS_APP_KEY / KIS_APP_SECRET 없음 (선택)"))

    if os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_KEY"):
        def supa():
            from stockeye.cloud.client import Supabase
            sb = Supabase()
            rows = sb.select("daily_reports", {"select": "date", "order": "date.desc", "limit": "1"})
            files = sb.list_files("data")
            uid = "있음" if os.getenv("SUPABASE_USER_ID") else "없음(⚠)"
            return f"최근 리포트 {rows[0]['date'] if rows else '없음'} · Storage data/ {len(files)}개 · USER_ID {uid}"
        check("Supabase", supa, res)
    else:
        res.append(("Supabase", "SKIP", "SUPABASE_URL / SUPABASE_SERVICE_KEY 없음"))

    print("\n" + "=" * 60)
    for name, st, msg in res:
        icon = {"OK": "✅", "FAIL": "❌", "SKIP": "➖"}[st]
        print(f"{icon} {name:<14} {msg}")
    print("=" * 60)
    if any(st == "FAIL" and name.startswith(("KRX", "KIS")) for name, st, _ in res):
        print("KRX/KIS 가 실패했다면: 해외 IP 차단일 수 있습니다 → 서울 리전 VM 에서 실행하세요 (deploy/vm/README.md)")
    sys.exit(1 if any(st == "FAIL" and name != "내 공인 IP" for name, st, _ in res) else 0)


if __name__ == "__main__":
    main()
