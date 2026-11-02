"""미국 선물 지수 (나스닥100 · S&P500 선물) 지금 등락률 — 당일단타의 '적극/보수' 판단용 (2026-11-02)

  출처  Yahoo Finance chart API (키 없음) — NQ=F · ES=F. 직전 정산가 대비 지금 등락률(%).
  ⚠ 클라우드 작업 공간에선 막혀 있어 PC(22번)에서만 받음 — 못 받으면 None (= 중립, 예전과 똑같이 동작)
  60~180초 캐시, 실패해도 예외를 밖으로 내지 않음
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger(__name__)

SYMBOLS = {"NQ": "NQ=F", "ES": "ES=F"}
URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=5m&range=1d"
TTL = 120
_cache: dict = {"at": 0.0, "val": None}


def parse(body: dict) -> float | None:
    """chart API 응답 → 등락률(%)"""
    try:
        meta = body["chart"]["result"][0]["meta"]
        px = float(meta["regularMarketPrice"])
        prev = float(meta.get("chartPreviousClose") or meta.get("previousClose"))
        return round((px / prev - 1) * 100, 2) if prev > 0 else None
    except Exception:  # noqa: BLE001
        return None


def fetch(force: bool = False) -> dict | None:
    """{'NQ': %, 'ES': %, 'at': 'HH:MM'} — 하나라도 받으면 그것만, 둘 다 실패하면 None"""
    if not force and time.time() - _cache["at"] < TTL:
        return _cache["val"]
    out: dict = {}
    try:
        import requests
        for k, sym in SYMBOLS.items():
            try:
                r = requests.get(URL.format(sym=sym), headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
                v = parse(r.json()) if r.ok else None
                if v is not None:
                    out[k] = v
            except Exception as e:  # noqa: BLE001
                log.debug("미국 선물 %s 실패: %s", sym, e)
    except Exception:  # noqa: BLE001
        pass
    val = ({**out, "at": time.strftime("%H:%M")} if out else None)
    _cache.update({"at": time.time(), "val": val})
    return val
