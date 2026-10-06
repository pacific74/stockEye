"""Supabase REST(PostgREST) + Storage 최소 클라이언트 (requests 만 사용)."""
from __future__ import annotations

import json
import logging
import os
import time

log = logging.getLogger(__name__)

BUCKET = "stockeye"


def enabled() -> bool:
    return bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_KEY"))


class SupabaseError(RuntimeError):
    pass


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=_default, allow_nan=False)


def _default(o):
    import math
    try:
        import numpy as np
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            f = float(o)
            return None if math.isnan(f) or math.isinf(f) else f
        if isinstance(o, np.bool_):
            return bool(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
    except ImportError:
        pass
    return str(o)


def clean(obj):
    """NaN/Inf → None (JSON 에 넣을 수 있게)."""
    import math
    if isinstance(obj, float):
        return None if math.isnan(obj) or math.isinf(obj) else obj
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    try:
        import numpy as np
        if isinstance(obj, np.generic):
            return clean(obj.item())
    except ImportError:
        pass
    return obj


class Supabase:
    def __init__(self, url: str | None = None, key: str | None = None, user_id: str | None = None):
        import requests
        self.url = (url or os.getenv("SUPABASE_URL") or "").rstrip("/")
        self.key = key or os.getenv("SUPABASE_SERVICE_KEY")
        self.user_id = user_id or os.getenv("SUPABASE_USER_ID")
        if not (self.url and self.key):
            raise SupabaseError("SUPABASE_URL / SUPABASE_SERVICE_KEY 환경변수가 없습니다")
        self.s = requests.Session()
        # 예전(Legacy) service_role 키는 JWT → apikey + Authorization 둘 다,
        # 새 secret 키(sb_secret_...)는 JWT 가 아니므로 apikey 헤더에만 넣는다 (Supabase 문서 기준)
        self.s.headers.update({"apikey": self.key})
        if not self.key.startswith("sb_"):
            self.s.headers["Authorization"] = f"Bearer {self.key}"

    # ------------------------------------------------------------ 공통
    def _req(self, method: str, path: str, *, retries: int = 3, **kw):
        last = None
        timeout = kw.pop("timeout", 60)
        for i in range(retries):
            try:
                r = self.s.request(method, self.url + path, timeout=timeout, **kw)
            except Exception as e:  # noqa: BLE001  (네트워크 일시 오류 재시도)
                last = e
                time.sleep(2 * (i + 1))
                continue
            if r.status_code >= 500 or r.status_code == 429:
                last = SupabaseError(f"{method} {path} → {r.status_code}: {r.text[:300]}")
                time.sleep(2 * (i + 1))
                continue
            return r
        raise SupabaseError(str(last))

    @staticmethod
    def _check(r, what: str):
        if r.status_code >= 300:
            raise SupabaseError(f"{what} 실패 {r.status_code}: {r.text[:400]}")
        return r

    # ------------------------------------------------------------ DB (PostgREST)
    def select(self, table: str, params: dict | None = None) -> list[dict]:
        r = self._check(self._req("GET", f"/rest/v1/{table}", params=params or {}), f"{table} 조회")
        return r.json()

    def insert(self, table: str, rows: list[dict] | dict, returning: bool = True) -> list[dict]:
        h = {"Content-Type": "application/json", "Prefer": "return=representation" if returning else "return=minimal"}
        r = self._check(self._req("POST", f"/rest/v1/{table}", headers=h, data=_dumps(clean(rows)).encode()),
                        f"{table} 추가")
        return r.json() if returning else []

    def upsert(self, table: str, rows: list[dict], on_conflict: str, chunk: int = 300) -> int:
        if not rows:
            return 0
        h = {"Content-Type": "application/json", "Prefer": "resolution=merge-duplicates,return=minimal"}
        for i in range(0, len(rows), chunk):
            part = clean(rows[i:i + chunk])
            self._check(self._req("POST", f"/rest/v1/{table}", headers=h, params={"on_conflict": on_conflict},
                                  data=_dumps(part).encode(), timeout=120), f"{table} 업로드")
        return len(rows)

    def update(self, table: str, filters: dict, patch: dict, returning: bool = False) -> list[dict]:
        h = {"Content-Type": "application/json", "Prefer": "return=representation" if returning else "return=minimal"}
        r = self._check(self._req("PATCH", f"/rest/v1/{table}", headers=h, params=filters,
                                  data=_dumps(clean(patch)).encode()), f"{table} 수정")
        return r.json() if returning else []

    def delete(self, table: str, filters: dict, returning: bool = False) -> list[dict]:
        h = {"Prefer": "return=representation" if returning else "return=minimal"}
        r = self._check(self._req("DELETE", f"/rest/v1/{table}", headers=h, params=filters), f"{table} 삭제")
        return r.json() if returning else []

    def count(self, table: str, params: dict) -> int:
        h = {"Prefer": "count=exact", "Range-Unit": "items", "Range": "0-0"}
        r = self._check(self._req("GET", f"/rest/v1/{table}", headers=h, params={**params, "select": "*"}),
                        f"{table} 개수")
        cr = r.headers.get("Content-Range", "*/0")
        return int(cr.split("/")[-1] or 0)

    # ------------------------------------------------------------ Storage
    def upload(self, path: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        h = {"Content-Type": content_type, "x-upsert": "true", "cache-control": "no-cache"}
        self._check(self._req("POST", f"/storage/v1/object/{BUCKET}/{path}", headers=h, data=data, timeout=300),
                    f"Storage 업로드 {path}")

    def download(self, path: str) -> bytes | None:
        r = self._req("GET", f"/storage/v1/object/{BUCKET}/{path}", timeout=300)
        if r.status_code in (400, 404):
            return None
        self._check(r, f"Storage 다운로드 {path}")
        return r.content

    def list_files(self, prefix: str) -> list[str]:
        h = {"Content-Type": "application/json"}
        out, offset = [], 0
        while True:
            r = self._check(self._req("POST", f"/storage/v1/object/list/{BUCKET}", headers=h,
                                      data=json.dumps({"prefix": prefix, "limit": 1000, "offset": offset})),
                            f"Storage 목록 {prefix}")
            items = r.json()
            out += [f"{prefix.rstrip('/')}/{it['name']}" for it in items if it.get("id")]
            if len(items) < 1000:
                return out
            offset += 1000
