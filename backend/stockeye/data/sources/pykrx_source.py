"""pykrx 기반 수집기 (KRX 공개 데이터, 무료).

날짜 단위로 '전 종목'을 한 번에 받는다 → 5년치도 영업일 수(약 1,250회)만큼만 호출.
  - 일봉 OHLCV + 거래대금      : stock.get_market_ohlcv(date, market="ALL")
  - 밸류에이션(EPS/BPS/PER/PBR): stock.get_market_fundamental(date, market="ALL")
  - 투자자별 순매수(금액)       : stock.get_market_net_purchases_of_equities(date, date, mkt, investor)

프로그램 매매(종목별)는 pykrx 에 없으므로 비워 둔다(점수 계산 시 자동 제외).
→ 필요하면 한국투자증권(KIS) Open API 로 sources/kis_source.py 를 추가.

로그인: pykrx 1.2.x 부터 KRX 정보데이터시스템 계정이 필요 → 환경변수 KRX_ID, KRX_PW.

주의: KRX 웹사이트 구조가 바뀌면 pykrx 가 일시적으로 깨질 수 있다.
      그럴 땐  pip install -U pykrx  로 업데이트.
"""
from __future__ import annotations

import logging
import time as _time

import pandas as pd

log = logging.getLogger(__name__)

INVESTORS = {"foreign": "외국인", "institution": "기관합계", "individual": "개인"}


def _stock():
    from pykrx import stock  # 지연 import (pykrx 없이도 나머지 코드 사용 가능)
    return stock


def _ymd(d) -> str:
    return pd.Timestamp(d).strftime("%Y%m%d")


class PykrxSource:
    def __init__(self, sleep: float = 0.3):
        self.sleep = sleep  # KRX 서버 부담/차단 방지용 호출 간격

    # ---------------- 영업일 ----------------
    def trading_days(self, start, end) -> list[pd.Timestamp]:
        stock = _stock()
        # 삼성전자 일봉 날짜 = 영업일 목록
        df = stock.get_market_ohlcv(_ymd(start), _ymd(end), "005930")
        return list(pd.to_datetime(df.index))

    # ---------------- 종목 리스트 ----------------
    def listing(self, date) -> pd.DataFrame:
        stock = _stock()
        rows = []
        for mkt in ("KOSPI", "KOSDAQ"):
            for code in stock.get_market_ticker_list(_ymd(date), market=mkt):
                rows.append({"code": code, "name": stock.get_market_ticker_name(code), "market": mkt})
            _time.sleep(self.sleep)
        df = pd.DataFrame(rows)
        df["is_admin"] = df["code"].isin(self.admin_codes())
        df["as_of"] = pd.Timestamp(date).normalize()
        return df

    def sectors(self, date) -> pd.DataFrame:
        """KRX 업종 분류 (코스피·코스닥)."""
        stock = _stock()
        parts = []
        for mkt in ("KOSPI", "KOSDAQ"):
            df = stock.get_market_sector_classifications(_ymd(date), mkt)
            if df is None or df.empty:
                continue
            df = df.reset_index()
            df = df.rename(columns={df.columns[0]: "code", "종목명": "name", "업종명": "sector", "시가총액": "marcap"})
            df["market"] = mkt
            # 시가총액: 업종 등락을 HTS 업종지수처럼 시가총액 가중으로 계산할 때 씀 (2026-10-13)
            parts.append(df[["code", "name", "sector", "market"] + (["marcap"] if "marcap" in df else [])])
            _time.sleep(self.sleep)
        if not parts:
            return pd.DataFrame()
        out = pd.concat(parts, ignore_index=True)
        out["code"] = out["code"].astype(str).str.zfill(6)
        out["as_of"] = pd.Timestamp(date).normalize()
        return out

    def admin_codes(self) -> set[str]:
        """관리종목 코드. FinanceDataReader 의 KRX-ADMIN 목록을 시도하고, 실패하면 빈 집합."""
        try:
            import FinanceDataReader as fdr
            df = fdr.StockListing("KRX-ADMIN")
            col = "Symbol" if "Symbol" in df else "Code"
            return set(df[col].astype(str).str.zfill(6))
        except Exception as e:  # noqa: BLE001
            log.warning("관리종목 목록 조회 실패(%s) → 관리종목 필터 비활성. 수동 목록을 data/admin.csv 로 둘 수 있음", e)
            return set()

    # ---------------- 하루치 전 종목 ----------------
    def ohlcv_day(self, date) -> pd.DataFrame:
        """코스피 + 코스닥 (코넥스 제외)."""
        stock = _stock()
        parts = []
        for mkt in ("KOSPI", "KOSDAQ"):
            df = stock.get_market_ohlcv(_ymd(date), market=mkt)
            if df is None or df.empty:
                continue
            df = df.rename(columns={"시가": "open", "고가": "high", "저가": "low", "종가": "close",
                                    "거래량": "volume", "거래대금": "value", "등락률": "chg_pct"})
            df.index.name = "code"
            cols = ["code", "open", "high", "low", "close", "volume", "value"] + (["chg_pct"] if "chg_pct" in df else [])
            df = df.reset_index()[cols]   # chg_pct(등락률)는 액면분할 보정에 사용
            # 거래정지 종목은 시/고/저가가 0으로 들어옴 → 종가로 채움
            for col in ("open", "high", "low"):
                df.loc[df[col] <= 0, col] = df["close"]
            parts.append(df)
            _time.sleep(self.sleep)
        if not parts:
            return pd.DataFrame()
        df = pd.concat(parts, ignore_index=True)
        df["date"] = pd.Timestamp(date).normalize()
        return df

    def fundamentals_day(self, date) -> pd.DataFrame:
        stock = _stock()
        df = stock.get_market_fundamental(_ymd(date), market="ALL")
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.rename(columns={"EPS": "eps", "BPS": "bps", "PER": "per", "PBR": "pbr", "DIV": "div"})
        df.index.name = "code"
        df = df.reset_index()[["code", "eps", "bps", "per", "pbr", "div"]]
        df["date"] = pd.Timestamp(date).normalize()
        return df

    def flows_day(self, date) -> pd.DataFrame:
        stock = _stock()
        parts = []
        for key, inv in INVESTORS.items():
            for mkt in ("KOSPI", "KOSDAQ"):
                try:
                    df = stock.get_market_net_purchases_of_equities(_ymd(date), _ymd(date), mkt, inv)
                except Exception as e:  # noqa: BLE001
                    log.warning("수급 조회 실패 %s %s %s: %s", date, mkt, inv, e)
                    continue
                if df is None or df.empty:
                    continue
                s = df["순매수거래대금"].rename(key)
                s.index.name = "code"
                parts.append(s)
                _time.sleep(self.sleep)
        if not parts:
            return pd.DataFrame()
        # 같은 투자자 키끼리 시장별로 이어붙인 뒤 가로로 합친다
        by_key: dict[str, list] = {}
        for s in parts:
            by_key.setdefault(s.name, []).append(s)
        wide = pd.concat({k: pd.concat(v) for k, v in by_key.items()}, axis=1)
        wide = wide[~wide.index.duplicated(keep="last")].reset_index()
        wide["program"] = float("nan")
        wide["date"] = pd.Timestamp(date).normalize()
        return wide

    def index_range(self, start, end) -> pd.DataFrame:
        stock = _stock()
        out = []
        for code, ticker in (("KOSPI", "1001"), ("KOSDAQ", "2001")):
            df = stock.get_index_ohlcv(_ymd(start), _ymd(end), ticker)
            df = df.rename(columns={"종가": "close"})[["close"]]
            df.index.name = "date"
            df = df.reset_index()
            df["code"] = code
            out.append(df)
        return pd.concat(out, ignore_index=True)
