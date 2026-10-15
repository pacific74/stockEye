"""당일매매 매수·매도 순간의 종합지수·업종지수 (2026-10-15) — 단타 결과가 시장·업종과 관련 있는지 보려고

  종합지수 = 그 종목 시장의 지수 (코스피 종목 → KOSPI · 코스닥 종목 → KOSDAQ) 전일 종가 대비 등락률 (네이버 지수 시세)
  업종지수 = 그 종목 업종(sectors 표)의 시가총액 큰 종목들(업종 시총 90% · 최대 60 · 자기 자신 뺌)의
             전일 대비 등락률을 시가총액으로 가중 평균 (네이버 시세 한 번에) — 장중 업종 등락 근사
  기록: track['ix'][키] = [종합 %, 업종 %, 'HH:MM', 'KOSPI'] · 키 = buy · t1 · t2 · t3 · even(매수가매도) · stop · close · sig
  매수 대비 변화 = (1 + 그때 %) / (1 + 매수 때 %) − 1
"""
from __future__ import annotations

import logging
import threading
import time

import pandas as pd

log = logging.getLogger(__name__)
CAP_SHARE, MAX_MEMBERS = 0.90, 60
CACHE_SEC = 15
KEY = {"매수발생": "buy", "1차목표달성": "t1", "2차목표달성": "t2", "3차목표달성": "t3", "매수가매도": "even",
       "본전 매도": "even", "손절": "stop", "마감 청산": "close", "매도신호포착": "sig"}


def members(code: str, sec_of: dict, caps: dict) -> list[str]:
    sec = sec_of.get(code)
    if not sec:
        return []
    mem = sorted([c for c, s in sec_of.items() if s == sec and c != code], key=lambda c: -caps.get(c, 0))
    tot, pick, acc = sum(caps.get(c, 0) for c in mem), [], 0.0
    for c in mem:
        pick.append(c)
        acc += caps.get(c, 0)
        if (tot and acc >= tot * CAP_SHARE) or len(pick) >= MAX_MEMBERS:
            break
    return pick


def weighted(chg: dict[str, float], caps: dict[str, float], codes: list[str]) -> float | None:
    w = [(chg[c], caps.get(c, 0)) for c in codes if c in chg and caps.get(c, 0) > 0]
    tot = sum(x for _, x in w)
    return round(sum(v * x for v, x in w) / tot, 2) if tot else None


def since(buy: float | None, now: float | None) -> float | None:
    """매수 때 등락률 → 지금 등락률: 매수 대비 변화 %"""
    if buy is None or now is None:
        return None
    return round(((1 + now / 100) / (1 + buy / 100) - 1) * 100, 2)


class IndexSnap:
    def __init__(self, listing: pd.DataFrame, sectors: pd.DataFrame | None, quotes=None, indices=None):
        from stockeye.data.sources import naver_live
        self.market = dict(zip(listing["code"], listing["market"])) if "market" in listing else {}
        self.sec_of = dict(zip(sectors["code"], sectors["sector"])) if sectors is not None and len(sectors) else {}
        self.caps = ({c: float(v) for c, v in zip(sectors["code"], sectors["marcap"]) if pd.notna(v) and v > 0}
                     if sectors is not None and "marcap" in sectors else {})
        self.quotes = quotes or naver_live.stocks
        self.indices = indices or naver_live.indices
        self._idx: tuple[float, dict] = (0.0, {})
        self.lock = threading.Lock()

    def _index(self) -> dict:
        with self.lock:
            if time.time() - self._idx[0] < CACHE_SEC:
                return self._idx[1]
        df = self.indices(("KOSPI", "KOSDAQ"))
        m = {str(r.code).upper(): float(r.chg_pct) for r in df.itertuples()} if df is not None and len(df) else {}
        with self.lock:
            self._idx = (time.time(), m)
        return m

    def snap(self, code: str) -> list | None:
        """[종합 %, 업종 %, 시장] — 못 받으면 None 칸"""
        mk = str(self.market.get(code) or "KOSPI").upper()
        mk = "KOSDAQ" if "KOSDAQ" in mk else "KOSPI"
        try:
            mkt = self._index().get(mk)
        except Exception as e:  # noqa: BLE001
            log.debug("지수 시세 실패: %s", e)
            mkt = None
        sec = None
        mem = members(code, self.sec_of, self.caps)
        if mem:
            try:
                q = self.quotes(mem)
                chg = {str(r.code): float(r.chg_pct) for r in q.itertuples()} if q is not None and len(q) else {}
                sec = weighted(chg, self.caps, mem)
            except Exception as e:  # noqa: BLE001
                log.debug("업종 시세 실패: %s", e)
        if mkt is None and sec is None:
            return None
        return [None if mkt is None else round(mkt, 2), sec, mk]
