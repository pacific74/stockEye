"""네이버 금융 실시간 시세 (장중 재분석용) — 전 종목 지금 가격으로 '오늘 봉(진행 중)'을 만든다.

  polling.finance.naver.com/api/realtime/domestic/stock/{코드,코드,…}   (한 번에 50개)
  polling.finance.naver.com/api/realtime/domestic/index/KOSPI,KOSDAQ

숫자는 '71,200' 같은 문자열, 부호는 compareToPreviousPrice.code (1·2 상승 / 3 보합 / 4·5 하락).
※ 공식 API 가 아니어서 형식이 바뀔 수 있다 → 해석 실패 종목은 건너뛰고, 대부분 실패하면 재분석을 하지 않는다.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

log = logging.getLogger(__name__)
BASE = "https://polling.finance.naver.com/api/realtime/domestic"
HEADERS = {"User-Agent": "Mozilla/5.0 (StockEye)", "Referer": "https://finance.naver.com/"}


def _num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except ValueError:
        return None


def _sign(c) -> int:
    if not isinstance(c, dict):
        return 0
    code, name = str(c.get("code", "")), str(c.get("name", "")).upper()
    if code in ("1", "2") or "RISING" in name or "UPPER" in name:
        return 1
    if code in ("4", "5") or "FALLING" in name or "LOWER" in name:
        return -1
    return 0


def parse_item(m: dict) -> dict | None:
    code = m.get("itemCode") or m.get("reutersCode") or m.get("symbolCode")
    price = _num(m.get("closePriceRaw") or m.get("closePrice"))
    if not code or price is None or price <= 0:
        return None
    s = _sign(m.get("compareToPreviousPrice"))
    ratio = _num(m.get("fluctuationsRatioRaw") or m.get("fluctuationsRatio"))
    if ratio is not None and s != 0:
        ratio = abs(ratio) * s
    vol = _num(m.get("accumulatedTradingVolumeRaw") or m.get("accumulatedTradingVolume")) or 0.0
    o = _num(m.get("openPriceRaw") or m.get("openPrice")) or price
    h = _num(m.get("highPriceRaw") or m.get("highPrice")) or max(o, price)
    lo = _num(m.get("lowPriceRaw") or m.get("lowPrice")) or min(o, price)
    t = pd.to_datetime(m.get("localTradedAt"), errors="coerce", utc=True)
    over = m.get("overMarketPriceInfo") if isinstance(m.get("overMarketPriceInfo"), dict) else {}
    o_px = _num(over.get("overPriceRaw") or over.get("overPrice")) if over else None
    return {"over_price": o_px, "over_status": over.get("overMarketStatus") if over else None,    # 넥스트레이드 프리·애프터마켓
            "over_session": over.get("tradingSessionType") if over else None,"code": str(code), "open": o, "high": max(h, o, price), "low": min(lo, o, price), "close": price,
            "volume": vol, "value": price * vol,      # 거래대금: 단위가 불확실한 필드 대신 가격×거래량 근사
            "chg_pct": ratio if ratio is not None else 0.0, "status": m.get("marketStatus"),
            "traded_at": t.tz_convert("Asia/Seoul").tz_localize(None) if pd.notna(t) else None}


def _get(kind: str, codes: list[str]) -> list[dict]:
    import requests
    for attempt in range(3):
        try:
            r = requests.get(f"{BASE}/{kind}/{','.join(codes)}", headers=HEADERS, timeout=15)
            js = r.json()
            datas = js.get("datas") or js.get("data") or []
            return [p for p in (parse_item(d) for d in datas if isinstance(d, dict)) if p]
        except Exception as ex:  # noqa: BLE001
            log.warning("네이버 시세 실패 (%s) 재시도 %d", ex, attempt + 1)
    return []


def stocks(codes: list[str], chunk: int = 50, workers: int = 6) -> pd.DataFrame:
    codes = sorted(set(codes))
    parts = [codes[i:i + chunk] for i in range(0, len(codes), chunk)]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        res = list(ex.map(lambda c: _get("stock", c), parts))
    rows = [r for part in res for r in part]
    got = {r["code"] for r in rows}
    miss = [c for c in codes if c not in got]
    if miss and len(miss) < len(codes) * 0.5:          # 여러 개 묶음이 안 되는 종목은 하나씩 (너무 많으면 생략)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for part in ex.map(lambda c: _get("stock", [c]), miss[:300]):
                rows += part
    return pd.DataFrame(rows)


def indices(codes=("KOSPI", "KOSDAQ")) -> pd.DataFrame:
    return pd.DataFrame(_get("index", list(codes)))


def is_trading_day(day: pd.Timestamp | None = None) -> bool | None:
    """오늘(또는 day) 한국 증시가 열렸나 — 주말 False, 지수 마지막 체결일이 그날이면 True, 아니면 False (휴장일).
    시세를 못 받으면 None (판단 불가 → 부르는 쪽에서 평소대로 진행)"""
    day = (day or pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None)).normalize()
    if day.weekday() >= 5:
        return False
    try:
        ix = indices(("KOSPI",))
        t = ix.iloc[0]["traded_at"] if not ix.empty else None
    except Exception as e:  # noqa: BLE001
        log.warning("휴장일 확인 실패: %s", e)
        return None
    if t is None or pd.isna(t):
        return None
    return pd.Timestamp(t).normalize() == day
