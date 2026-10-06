"""parquet 저장소.

데이터셋 (모두 긴 형식):
  ohlcv.parquet        date, code, open, high, low, close, volume, value
  flows.parquet        date, code, foreign, institution, individual, program   (순매수 금액, 원)
  fundamentals.parquet date, code, eps, bps, per, pbr, div
  disclosures.parquet  code, published_at(datetime), title, source
  listing.parquet      code, name, market, is_admin, as_of
  index.parquet        date, code(KOSPI/KOSDAQ), close         (벤치마크)
  sectors.parquet      code, name, market, sector, as_of       (KRX 업종 분류)
  program.parquet      date, code, program                      (KIS 종목별 프로그램 순매수 금액)
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

DATASETS = ("ohlcv", "flows", "fundamentals", "disclosures", "listing", "index", "sectors", "program")
KEYS = {
    "ohlcv": ["date", "code"], "flows": ["date", "code"], "fundamentals": ["date", "code"],
    "disclosures": ["code", "published_at", "title"], "listing": ["code"], "index": ["date", "code"],
    "sectors": ["code"], "program": ["date", "code"],
}


class DataStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, name: str) -> Path:
        assert name in DATASETS, name
        return self.root / f"{name}.parquet"

    def load(self, name: str) -> pd.DataFrame:
        p = self.path(name)
        if not p.exists():
            return pd.DataFrame()
        df = pd.read_parquet(p)
        if "date" in df:
            df["date"] = pd.to_datetime(df["date"])
        if "published_at" in df:
            df["published_at"] = pd.to_datetime(df["published_at"])
        return df

    def save(self, name: str, df: pd.DataFrame) -> None:
        df.to_parquet(self.path(name), index=False)

    def upsert(self, name: str, new: pd.DataFrame) -> pd.DataFrame:
        """기존 데이터와 합치고 키 기준 중복 제거 (새 데이터 우선)."""
        if new is None or new.empty:
            return self.load(name)
        old = self.load(name)
        df = pd.concat([old, new], ignore_index=True) if not old.empty else new.copy()
        df = df.drop_duplicates(subset=KEYS[name], keep="last")
        sort_cols = [c for c in ("date", "code") if c in df] or KEYS[name]
        df = df.sort_values(sort_cols).reset_index(drop=True)
        self.save(name, df)
        return df

    def last_date(self, name: str = "ohlcv") -> pd.Timestamp | None:
        df = self.load(name)
        return None if df.empty else df["date"].max()
