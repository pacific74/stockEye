"""기업 개요 (종목 화면 맨 위 요약용).

  - KIND(한국거래소 기업공시채널) 상장법인 목록: 업종 · 주요제품 · 상장일 · 결산월 · 대표자 · 홈페이지 · 지역
    → 자주 바뀌지 않으므로 주 1회만 받아서 캐시
  - 상장주식수 (pykrx) → 시가총액 = 최근 종가 × 상장주식수
  - PER / PBR / 배당수익률 / EPS / BPS: 이미 모으는 fundamentals 의 최근 값
  - KRX 업종 분류: 이미 모으는 sectors

모두 '참고용 현재 정보'이며 점수 계산에는 쓰지 않는다 (미래참조 영향 없음).
"""
from __future__ import annotations

import io
import logging
import math

import pandas as pd

log = logging.getLogger(__name__)

KIND_URL = "https://kind.krx.co.kr/corpgeneral/corpList.do"

_KIND_COLS = {
    "회사명": "name", "종목코드": "code", "업종": "industry", "주요제품": "products", "상장일": "listed",
    "결산월": "fiscal_month", "대표자명": "ceo", "홈페이지": "homepage", "지역": "region",
}


def fetch_kind(timeout: int = 30) -> pd.DataFrame:
    """KIND 상장법인 목록 전체 (코스피·코스닥·코넥스)."""
    import requests
    r = requests.get(KIND_URL, params={"method": "download", "searchType": "13"}, timeout=timeout,
                     headers={"User-Agent": "Mozilla/5.0 (StockEye)"})
    r.raise_for_status()
    text = r.content.decode("euc-kr", errors="replace")
    df = pd.read_html(io.StringIO(text), header=0)[0]
    df = df.rename(columns={k: v for k, v in _KIND_COLS.items() if k in df.columns})
    df["code"] = df["code"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    keep = [c for c in _KIND_COLS.values() if c in df.columns]
    return df[keep].drop_duplicates("code", keep="last")


def fetch_shares(date) -> dict[str, int]:
    """상장주식수 {code: 주식수} (pykrx, 실패하면 빈 dict)."""
    try:
        from pykrx import stock
        df = stock.get_market_cap(pd.Timestamp(date).strftime("%Y%m%d"), market="ALL")
        col = "상장주식수" if "상장주식수" in df.columns else df.columns[-1]
        return {str(c).zfill(6): int(v) for c, v in df[col].items() if pd.notna(v) and v > 0}
    except Exception as e:  # noqa: BLE001
        log.warning("상장주식수 조회 실패(%s) → 시가총액 생략", e)
        return {}


def fetch_company_meta(date) -> dict:
    """주 1회 캐시할 원본: {fetched_at, rows: {code: {...KIND 칸..., shares}}}"""
    rows: dict[str, dict] = {}
    try:
        kind = fetch_kind()
        for r in kind.to_dict("records"):
            rows[r["code"]] = {k: (None if (isinstance(v, float) and math.isnan(v)) else v)
                               for k, v in r.items() if k != "code"}
        log.info("KIND 기업 개요 %d개", len(rows))
    except Exception as e:  # noqa: BLE001
        log.warning("KIND 기업 개요 조회 실패(%s) → 업종·주요제품 생략", e)
    for code, n in fetch_shares(date).items():
        rows.setdefault(code, {})["shares"] = n
    return {"fetched_at": str(pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None))[:19], "rows": rows}


def is_stale(meta: dict | None, days: int = 7) -> bool:
    if not meta or not meta.get("rows"):
        return True
    try:
        return pd.Timestamp.now(tz="Asia/Seoul").tz_localize(None) - pd.Timestamp(meta["fetched_at"]) > pd.Timedelta(days=days)
    except Exception:  # noqa: BLE001
        return True


def _num(v, nd=2):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, nd)


def build_profiles(view, meta: dict | None, sectors: pd.DataFrame | None, listing: pd.DataFrame | None,
                   codes) -> dict[str, dict]:
    """종목별 개요 {code: {market, sector, industry, products, …, market_cap, per, pbr, div}}"""
    rows = (meta or {}).get("rows", {})
    sector_of = dict(zip(sectors["code"], sectors["sector"])) if sectors is not None and not sectors.empty else {}
    market_of = {}
    if listing is not None and not listing.empty:
        market_of = dict(zip(listing["code"], listing["market"]))

    oh = view.ohlcv()
    last_close = oh.sort_values("date").groupby("code")["close"].last().to_dict() if not oh.empty else {}
    try:
        fu = view.fundamentals()
        fund = fu.sort_values("date").groupby("code").last() if not fu.empty else pd.DataFrame()
    except Exception:  # noqa: BLE001
        fund = pd.DataFrame()

    out = {}
    for code in codes:
        k = rows.get(code, {})
        p = {
            "market": market_of.get(code),
            "sector": sector_of.get(code),
            "industry": k.get("industry"),
            "products": k.get("products"),
            "listed": str(k["listed"])[:10] if k.get("listed") else None,
            "fiscal_month": k.get("fiscal_month"),
            "ceo": k.get("ceo"),
            "homepage": k.get("homepage"),
            "region": k.get("region"),
        }
        sh, px = k.get("shares"), last_close.get(code)
        p["market_cap"] = int(sh * px) if sh and px else None
        if code in fund.index:
            f = fund.loc[code]
            for col in ("per", "pbr", "div", "eps", "bps"):
                if col in f.index:
                    v = _num(f[col])
                    p[col] = v if v not in (0, 0.0) or col == "div" else None
        out[code] = {k2: v for k2, v in p.items() if v not in (None, "", "nan")}
    return out
