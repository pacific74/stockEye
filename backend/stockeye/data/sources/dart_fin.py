"""DART 재무 (다중회사 주요계정 fnlttMultiAcnt) 수집기.

한 번에 최대 100개 회사 × (연도, 보고서) 를 받는다.
  보고서 코드: 11013 1분기 / 11012 반기 / 11014 3분기 / 11011 사업보고서(연간)
  5년치 전 종목 ≈ 연 6개 × 보고서 4개 × 28묶음 ≈ 700회 호출 (하루 한도 2만 회)

[미래참조 주의] 재무 숫자는 '기간 말일'이 아니라 '접수일'(rcept_no 앞 8자리) 다음 날부터 쓸 수 있다.
  → date 칸 = 접수일 23:59 (공시 목록과 같은 규칙). 백테스트·분석은 date 이전 값만 본다.

결과 (financials.parquet, 긴 형식이 아니라 보고서 1건 = 1행):
  code, date(이용 가능 시각), year, reprt(Q1/H1/Q3/FY), fs(CFS/OFS),
  revenue, op_income, net_income      ← 손익: 해당 연도 누적(YTD)
  assets, liabilities, equity, capital, cur_assets, cur_liab   ← 재무상태: 기간 말
"""
from __future__ import annotations

import io
import logging
import re
import os
import time as _time
import zipfile
import xml.etree.ElementTree as ET

import pandas as pd

log = logging.getLogger(__name__)

BASE = "https://opendart.fss.or.kr/api"
REPRT = {"11013": "Q1", "11012": "H1", "11014": "Q3", "11011": "FY"}
REPRT_ORDER = {"Q1": 1, "H1": 2, "Q3": 3, "FY": 4}

# 주요계정 이름 → 칸 (회사마다 이름이 조금씩 달라 앞부분/포함으로 찾는다)
ACCOUNTS = [
    ("revenue", ("매출액", "수익(매출액)", "영업수익", "매출")),
    ("op_income", ("영업이익", "영업이익(손실)", "영업손익")),
    ("net_income", ("당기순이익", "당기순이익(손실)", "당기순손익", "분기순이익", "반기순이익")),
    ("assets", ("자산총계",)),
    ("liabilities", ("부채총계",)),
    ("equity", ("자본총계",)),
    ("capital", ("자본금",)),
    ("cur_assets", ("유동자산",)),
    ("cur_liab", ("유동부채",)),
]


def _amount(v) -> float | None:
    if v is None:
        return None
    s = str(v).replace(",", "").strip()
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _match(name: str) -> str | None:
    n = name.replace(" ", "")
    for col, keys in ACCOUNTS:
        for k in keys:
            if n == k or n.startswith(k):
                # '매출'로 시작하지만 매출원가·매출총이익은 제외
                if col == "revenue" and ("원가" in n or "총이익" in n):
                    return None
                if col == "net_income" and ("지배" in n or "비지배" in n):
                    return None
                return col
    return None


class DartFinancials:
    def __init__(self, api_key: str | None = None, sleep: float = 0.15):
        self.key = api_key or os.getenv("DART_API_KEY")
        self.sleep = sleep
        self.limit_hit = False
        self.calls = 0

    # ---------------------------------------------------------------- 회사 코드
    def corp_codes(self) -> dict[str, str]:
        """{종목코드: DART 고유번호(corp_code)} — 상장사만"""
        import requests
        r = requests.get(f"{BASE}/corpCode.xml", params={"crtfc_key": self.key}, timeout=60)
        r.raise_for_status()
        self.calls += 1
        z = zipfile.ZipFile(io.BytesIO(r.content))
        root = ET.fromstring(z.read(z.namelist()[0]))
        out = {}
        for el in root.iter("list"):
            sc = (el.findtext("stock_code") or "").strip()
            cc = (el.findtext("corp_code") or "").strip()
            if sc and cc:
                out[sc] = cc
        log.info("DART 회사 코드 %d개 (상장)", len(out))
        return out

    # ---------------------------------------------------------------- 재무
    def fetch(self, codes: list[str], years: list[int], reprts=("11013", "11012", "11014", "11011"),
              corp_map: dict[str, str] | None = None, workers: int = 8, deadline: float | None = None) -> pd.DataFrame:
        """여러 묶음(100개 회사)을 동시에 요청 (DART 응답이 1건에 수십 초 걸릴 때가 있어 순서대로 하면 매우 느림).
        deadline(time.time() 기준) 을 넘기면 남은 요청은 건너뜀. 실패한 묶음 수는 self.failed 에."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        if not self.key:
            log.warning("DART_API_KEY 없음 → 재무 수집 생략")
            return pd.DataFrame()
        corp_map = corp_map or self.corp_codes()
        pairs = [(c, corp_map[c]) for c in codes if c in corp_map]
        jobs = [(y, rc, [cc for _, cc in pairs[i:i + 100]]) for y in years for rc in reprts
                for i in range(0, len(pairs), 100)]
        rows: list[dict] = []
        self.failed = 0
        with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            futs = {ex.submit(self._multi_safe, cc, y, rc, deadline): (y, rc) for y, rc, cc in jobs}
            for f in as_completed(futs):
                got = f.result()
                if got is None:
                    self.failed += 1
                else:
                    rows += got
        if self.limit_hit:
            log.warning("DART 하루 호출 한도 초과 → 일부만 받음 (내일 이어서)")
        log.info("DART 재무 %s %s: %d건 (요청 %d묶음, 실패 %d, 누적 호출 %d)",
                 years, [REPRT[r] for r in reprts], len(rows), len(jobs), self.failed, self.calls)
        return pd.DataFrame(rows)

    def _multi_safe(self, corp_codes, year, reprt_code, deadline=None):
        if self.limit_hit or (deadline is not None and _time.time() > deadline):
            return None
        try:
            return self._multi(corp_codes, year, reprt_code)
        except Exception as ex:  # noqa: BLE001
            log.warning("DART 재무 묶음 실패 %s %s: %s", year, reprt_code, ex)
            return None

    def _multi(self, corp_codes: list[str], year: int, reprt_code: str) -> list[dict] | None:
        """None = 실패(다시 받아야 함) / [] = 자료 없음"""
        import requests
        js = None
        for attempt in range(3):
            try:
                r = requests.get(f"{BASE}/fnlttMultiAcnt.json", params={
                    "crtfc_key": self.key, "corp_code": ",".join(corp_codes),
                    "bsns_year": str(year), "reprt_code": reprt_code}, timeout=120)
                self.calls += 1
                js = r.json()
                break
            except Exception as ex:  # noqa: BLE001
                log.warning("DART 재무 요청 실패 (%s) 재시도 %d", ex, attempt + 1)
                _time.sleep(3 * (attempt + 1))
        if js is None:
            return None
        st = js.get("status")
        if st != "000":
            if st == "020":
                self.limit_hit = True
                return None
            if st == "013":          # 자료 없음
                return []
            log.warning("DART 재무 오류 %s: %s", st, js.get("message"))
            return None
        return parse_multi(js.get("list", []), year, reprt_code)


PERIODIC = re.compile(r"(분기|반기|사업)보고서\s*\((\d{4})\.(\d{2})\)")


def periodic_filings(disc: pd.DataFrame, since: pd.Timestamp) -> dict[tuple[int, str], set[str]]:
    """최근 공시 중 정기보고서 제출 → {(사업연도, 보고서코드): 종목들}  (일일 배치는 이것만 새로 받음)
    예: '반기보고서 (2026.06)' → (2026, '11012') / '사업보고서 (2025.12)' → (2025, '11011')"""
    out: dict[tuple[int, str], set[str]] = {}
    if disc is None or disc.empty:
        return out
    d = disc[pd.to_datetime(disc["published_at"]) >= since]
    for code, title in zip(d["code"], d["title"]):
        m = PERIODIC.search(str(title).replace(" (", " ("))
        if not m:
            continue
        kind, y, mm = m.group(1), int(m.group(2)), int(m.group(3))
        if kind == "사업":
            rc = "11011"
        elif kind == "반기":
            rc = "11012"
        else:
            rc = "11013" if mm <= 4 else "11014"
        out.setdefault((y, rc), set()).add(code)
    return out


def parse_multi(items: list[dict], year: int, reprt_code: str) -> list[dict]:
    """fnlttMultiAcnt 응답 → 회사·보고서별 1행 (연결 CFS 우선, 없으면 별도 OFS)"""
    by: dict[tuple, dict] = {}
    for it in items:
        code = (it.get("stock_code") or "").strip()
        if not code:
            continue
        fs = it.get("fs_div") or "OFS"
        col = _match(it.get("account_nm") or "")
        if col is None:
            continue
        key = (code, fs)
        row = by.setdefault(key, {"code": code, "fs": fs, "year": int(year), "reprt": REPRT[reprt_code],
                                  "rcept_no": it.get("rcept_no")})
        is_flow = col in ("revenue", "op_income", "net_income")
        v = _amount(it.get("thstrm_add_amount")) if is_flow else None
        if v is None:
            v = _amount(it.get("thstrm_amount"))
        if v is not None and row.get(col) is None:
            row[col] = v
    out = {}
    for (code, fs), row in by.items():
        if code in out and out[code]["fs"] == "CFS":
            continue
        out[code] = row
    rows = []
    for row in out.values():
        rn = str(row.get("rcept_no") or "")
        if len(rn) < 8:
            continue
        row["date"] = pd.Timestamp(rn[:8]) + pd.Timedelta(hours=23, minutes=59)
        rows.append(row)
    return rows
