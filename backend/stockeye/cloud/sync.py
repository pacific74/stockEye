"""원본 데이터(parquet)를 Supabase Storage 와 주고받기.

Storage 구조 (버킷 'stockeye'):
  data/manifest.json                 각 조각의 내용 해시
  data/ohlcv/2021.parquet ...        큰 데이터는 연도별로 쪼갬 (무료 요금제 파일당 50MB 제한 대비)
  data/flows/2021.parquet ...
  data/listing.parquet ...           작은 데이터는 통째로

pull(): 로컬에 없거나 해시가 다른 조각만 받아서 data/*.parquet 로 합친다.
push(): 바뀐 조각만 올린다 (매일 올라가는 건 보통 올해 조각 몇 개).
로컬 data/ 폴더 형식은 그대로라서 수집·분석 코드는 바뀌지 않는다.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
from pathlib import Path

import pandas as pd

from ..data.store import DataStore, DATASETS
from .client import Supabase

log = logging.getLogger(__name__)

PREFIX = "data"
YEARLY = {"ohlcv": "date", "flows": "date", "fundamentals": "date", "program": "date", "disclosures": "published_at",
          "financials": "date"}


def _hash(df: pd.DataFrame) -> str:
    h = hashlib.md5()
    h.update(",".join(map(str, df.columns)).encode())
    d = df.copy()
    for c in d.columns:     # 저장 형식에 따라 시간 단위(ns/us)가 달라져도 같은 해시가 되도록
        if pd.api.types.is_datetime64_dtype(d[c]):          # 시간대 없는 날짜만
            d[c] = d[c].astype("datetime64[ns]")
    h.update(pd.util.hash_pandas_object(d, index=False).values.tobytes())
    return h.hexdigest()


def _to_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    return buf.getvalue()


def parts_of(store: DataStore, name: str) -> dict[str, pd.DataFrame]:
    """로컬 데이터셋을 업로드 조각으로 나눔. key = Storage 경로."""
    df = store.load(name)
    if df.empty:
        return {}
    col = YEARLY.get(name)
    if col is None or col not in df:
        return {f"{PREFIX}/{name}.parquet": df}
    df = df.sort_values([c for c in (col, "code") if c in df], kind="stable").reset_index(drop=True)
    years = pd.to_datetime(df[col]).dt.year
    return {f"{PREFIX}/{name}/{int(y)}.parquet": g.reset_index(drop=True) for y, g in df.groupby(years)}


class DataSync:
    def __init__(self, store: DataStore, sb: Supabase | None = None):
        self.store = store
        self.sb = sb or Supabase()
        self.local_manifest_path = Path(store.root) / ".cloud_manifest.json"

    # ------------------------------------------------------------ manifest
    def remote_manifest(self) -> dict:
        b = self.sb.download(f"{PREFIX}/manifest.json")
        return json.loads(b) if b else {}

    def _local_manifest(self) -> dict:
        p = self.local_manifest_path
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    def _save_local_manifest(self, m: dict) -> None:
        self.local_manifest_path.write_text(json.dumps(m, indent=1), encoding="utf-8")

    # ------------------------------------------------------------ push
    def push(self, datasets=DATASETS, force: bool = False) -> list[str]:
        remote = {} if force else self.remote_manifest()
        manifest = dict(remote)
        uploaded = []
        for name in datasets:
            parts = parts_of(self.store, name)
            # 이 데이터셋의 기존 조각 중 로컬에 없는 연도는 manifest 에서 지움 (데이터가 줄어든 경우)
            for k in [k for k in manifest if k.startswith(f"{PREFIX}/{name}/") or k == f"{PREFIX}/{name}.parquet"]:
                if k not in parts:
                    manifest.pop(k)
            for key, df in parts.items():
                h = _hash(df)
                if not force and remote.get(key) == h:
                    continue
                data = _to_bytes(df)
                if len(data) > 48 * 1024 * 1024:
                    log.warning("%s 가 %.0fMB 입니다 (무료 요금제 파일당 50MB 제한)", key, len(data) / 1e6)
                self.sb.upload(key, data)
                manifest[key] = h
                uploaded.append(key)
                log.info("업로드 %s (%d행, %.1fMB)", key, len(df), len(data) / 1e6)
        self.sb.upload(f"{PREFIX}/manifest.json", json.dumps(manifest, indent=1).encode(), "application/json")
        self._save_local_manifest(manifest)
        return uploaded

    # ------------------------------------------------------------ pull
    def pull(self, datasets=DATASETS) -> list[str]:
        remote = self.remote_manifest()
        if not remote:
            log.warning("Storage 에 데이터가 없습니다. PC 에서 먼저  python -m scripts.cloud_push  를 실행하세요.")
            return []
        local = self._local_manifest()
        changed = []
        for name in datasets:
            keys = sorted(k for k in remote if k.startswith(f"{PREFIX}/{name}/") or k == f"{PREFIX}/{name}.parquet")
            if not keys:
                continue
            path = self.store.path(name)
            same = path.exists() and all(local.get(k) == remote[k] for k in keys) and \
                set(k for k in local if k.startswith(f"{PREFIX}/{name}/") or k == f"{PREFIX}/{name}.parquet") == set(keys)
            if same:
                continue
            frames = []
            for k in keys:
                b = self.sb.download(k)
                if b is None:
                    raise RuntimeError(f"Storage 에 {k} 가 없습니다 (manifest 와 불일치)")
                frames.append(pd.read_parquet(io.BytesIO(b)))
            df = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
            self.store.save(name, df)
            changed.append(name)
            log.info("내려받음 %s (%d조각, %d행)", name, len(keys), len(df))
        self._save_local_manifest(remote)
        return changed

    # ------------------------------------------------------------ 기타 파일 (리포트 등)
    def put_json(self, key: str, obj) -> None:
        self.sb.upload(key, json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"), "application/json")

    def get_json(self, key: str):
        b = self.sb.download(key)
        return json.loads(b) if b else None
