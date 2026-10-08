"""Point-In-Time(시점 고정) 데이터 접근 계층.

    "2025-10-10 09:30 에 계산한다면, 그 시각 이전에 '공개된' 데이터만 쓴다."

각 데이터는 '날짜'가 아니라 '공개 시각(available_at)' 기준으로 걸러진다.
  - 일봉(D일)        → D일 15:30 장 마감 후에야 존재
  - 투자자 수급(D일)  → D일 18:00 (KRX 확정치 공개 이후)
  - 밸류에이션(D일)   → D일 18:00
  - 공시/뉴스        → 공시 접수 시각 그대로

예) as_of = 2025-10-10 09:30  → 10월 10일 일봉/수급은 아직 '미래'라서 보이지 않음.
    as_of = 2025-10-10 15:30  → 10월 10일 일봉은 보이지만 수급은 아직 안 보임.
    as_of = 2025-10-10 18:00  → 둘 다 보임 (→ 다음날 시가 매수 결정용).

미래 데이터를 요청하면 FutureDataError 를 던져서 프로그램이 멈춘다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time

import pandas as pd


class FutureDataError(RuntimeError):
    """as_of 시점 이후의 데이터에 접근하려 할 때 발생."""


# 데이터셋별 공개 시각 (D일 데이터가 공개되는 시각)
AVAILABLE_TIME = {
    "ohlcv": time(15, 30),
    "flows": time(18, 0),
    "fundamentals": time(18, 0),
    "index": time(15, 30),
}

MARKET_CLOSE = time(15, 30)
DECISION_TIME = time(18, 0)   # 장 마감 후 분석 → 다음날 시가 매수


def at(date, t: time) -> pd.Timestamp:
    d = pd.Timestamp(date).normalize()
    return d + pd.Timedelta(hours=t.hour, minutes=t.minute)


def available_at(dataset: str, dates: pd.Series | pd.DatetimeIndex) -> pd.Series:
    t = AVAILABLE_TIME[dataset]
    d = pd.to_datetime(pd.Series(dates)).dt.normalize()
    return d + pd.Timedelta(hours=t.hour, minutes=t.minute)


def last_available_date(dataset: str, as_of: pd.Timestamp) -> pd.Timestamp:
    """as_of 시점에 볼 수 있는 dataset의 마지막 '날짜'."""
    as_of = pd.Timestamp(as_of)
    t = AVAILABLE_TIME[dataset]
    cutoff = at(as_of, t)
    return as_of.normalize() if as_of >= cutoff else as_of.normalize() - pd.Timedelta(days=1)


@dataclass
class PITView:
    """특정 시각(as_of)에 '알 수 있었던' 데이터만 노출하는 읽기 전용 뷰."""
    as_of: pd.Timestamp
    _ohlcv: pd.DataFrame
    _flows: pd.DataFrame
    _fund: pd.DataFrame
    _disc: pd.DataFrame
    _index: pd.DataFrame
    _listing: pd.DataFrame
    access_log: list = field(default_factory=list)

    # -- 내부 필터 -------------------------------------------------------
    def _cut(self, df: pd.DataFrame, dataset: str) -> pd.DataFrame:
        if df.empty:
            return df
        last = last_available_date(dataset, self.as_of)
        out = df[df["date"] <= last]
        self.access_log.append((dataset, last))
        return out

    def _check_end(self, end, dataset: str):
        if end is None:
            return
        last = last_available_date(dataset, self.as_of)
        if pd.Timestamp(end).normalize() > last:
            raise FutureDataError(
                f"[미래참조 차단] as_of={self.as_of} 에서 {dataset} {pd.Timestamp(end).date()} 데이터를 요청함 "
                f"(사용 가능한 마지막 날짜: {last.date()})"
            )

    # -- 공개 API ---------------------------------------------------------
    def ohlcv(self, codes=None, end=None) -> pd.DataFrame:
        self._check_end(end, "ohlcv")
        df = self._cut(self._ohlcv, "ohlcv")
        return df if codes is None else df[df["code"].isin(_as_list(codes))]

    def flows(self, codes=None, end=None) -> pd.DataFrame:
        self._check_end(end, "flows")
        df = self._cut(self._flows, "flows")
        return df if codes is None else df[df["code"].isin(_as_list(codes))]

    def fundamentals(self, codes=None, end=None) -> pd.DataFrame:
        self._check_end(end, "fundamentals")
        df = self._cut(self._fund, "fundamentals")
        return df if codes is None else df[df["code"].isin(_as_list(codes))]

    def index(self, end=None) -> pd.DataFrame:
        self._check_end(end, "index")
        return self._cut(self._index, "index")

    def disclosures(self, codes=None, since_days: int = 5) -> pd.DataFrame:
        df = self._disc
        if df.empty:
            return df
        df = df[(df["published_at"] <= self.as_of)
                & (df["published_at"] > self.as_of - pd.Timedelta(days=since_days))]
        self.access_log.append(("disclosures", self.as_of))
        return df if codes is None else df[df["code"].isin(_as_list(codes))]

    def listing(self) -> pd.DataFrame:
        # 주의: 종목 리스트/관리종목은 '현재 스냅샷'만 보관 중이면 과거 백테스트에서
        #       생존편향을 만든다. as_of 컬럼이 있으면 그 시점 이전 스냅샷만 사용.
        df = self._listing
        if df.empty or "as_of" not in df:
            return df
        snap = df[pd.to_datetime(df["as_of"]) <= self.as_of]
        return snap if not snap.empty else df.iloc[0:0]

    def trading_dates(self) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(sorted(self.ohlcv()["date"].unique()))


class PointInTimeData:
    """전체 데이터를 들고 있다가, as_of 별로 PITView 를 발급한다."""

    def __init__(self, ohlcv, flows=None, fund=None, disclosures=None, index=None, listing=None):
        e = pd.DataFrame
        self.ohlcv = _norm(ohlcv)
        self.flows = _norm(flows if flows is not None else e())
        self.fund = _norm(fund if fund is not None else e())
        self.disc = disclosures if disclosures is not None else e()
        self.index = _norm(index if index is not None else e())
        self.listing = listing if listing is not None else e()
        self.sectors = e()      # 업종 분류 (현재 스냅샷; 그룹핑 용도라 미래참조 영향 작음)
        self.financials = e()   # DART 주요계정 (date = 접수일 → 그 뒤에만 사용)

    @classmethod
    def from_store(cls, store) -> "PointInTimeData":
        flows = store.load("flows")
        prog = store.load("program")
        if not prog.empty and not flows.empty:   # KIS 프로그램매매를 수급 테이블에 합침
            flows = flows.drop(columns=["program"], errors="ignore").merge(
                prog[["date", "code", "program"]], on=["date", "code"], how="left")
        obj = cls(store.load("ohlcv"), flows, store.load("fundamentals"),
                  store.load("disclosures"), store.load("index"), store.load("listing"))
        obj.sectors = store.load("sectors")
        obj.financials = store.load("financials")
        return obj

    def view(self, as_of) -> PITView:
        return PITView(pd.Timestamp(as_of), self.ohlcv, self.flows, self.fund,
                       self.disc, self.index, self.listing)

    def trading_dates(self) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(sorted(self.ohlcv["date"].unique()))


def _as_list(x):
    return [x] if isinstance(x, str) else list(x)


def _norm(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["date", "code"])
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    return df.sort_values(["date", "code"]).reset_index(drop=True)
