"""DART(전자공시) Open API 수집기.

API 키: https://opendart.fss.or.kr 에서 무료 발급 → 환경변수 DART_API_KEY 에 저장.

[미래참조 주의] DART 목록 API 의 접수일(rcept_dt)에는 '시각'이 없다.
→ 보수적으로 접수일 23:59 에 공개된 것으로 처리한다.
  (장중 공시를 같은 날 종가 판단에 쓰면 미래참조가 될 수 있기 때문)
"""
from __future__ import annotations

import logging
import os
import time as _time

import pandas as pd

log = logging.getLogger(__name__)
URL = "https://opendart.fss.or.kr/api/list.json"


class DartSource:
    def __init__(self, api_key: str | None = None, sleep: float = 0.2):
        self.key = api_key or os.getenv("DART_API_KEY")
        self.sleep = sleep

    def disclosures(self, start, end) -> pd.DataFrame:
        """코스피(Y)·코스닥(K) 공시만, 1개월 단위로 받는다.
        - 회사 지정 없이 조회하면 기간이 3개월로 제한됨
        - 하루 호출 한도(약 2만 회)가 있어 비상장/기타법인은 처음부터 제외
        """
        if not self.key:
            log.warning("DART_API_KEY 없음 → 공시 수집 생략 (뉴스/공시 점수는 중립 처리)")
            return pd.DataFrame()
        parts = []
        s, e = pd.Timestamp(start), pd.Timestamp(end)
        self.limit_hit = False
        while s <= e and not self.limit_hit:
            m_end = min(s + pd.offsets.MonthEnd(0), e)
            for cls in ("Y", "K"):
                parts.append(self._fetch(s, m_end, cls))
            n = sum(len(p) for p in parts)
            log.info("DART 공시 %s ~ %s (누적 %d건)", s.date(), m_end.date(), n)
            s = m_end + pd.Timedelta(days=1)
        if self.limit_hit:
            log.warning("DART 하루 호출 한도 초과 → %s 이후는 내일 다시: python -m scripts.collect --dart-only --start %s",
                        s.date(), s.date())
        parts = [p for p in parts if not p.empty]
        return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()

    def _fetch(self, start, end, corp_cls: str) -> pd.DataFrame:
        import requests
        rows, page = [], 1
        while True:
            try:
                r = requests.get(URL, params={
                    "crtfc_key": self.key, "corp_cls": corp_cls,
                    "bgn_de": pd.Timestamp(start).strftime("%Y%m%d"),
                    "end_de": pd.Timestamp(end).strftime("%Y%m%d"), "page_no": page, "page_count": 100,
                }, timeout=20)
                js = r.json()
            except Exception as ex:  # noqa: BLE001
                log.warning("DART 요청 실패 (%s), 건너뜀", ex)
                break
            st = js.get("status")
            if st != "000":
                if st == "020":          # 요청 제한 초과
                    self.limit_hit = True
                elif st != "013":        # 013 = 조회 결과 없음
                    log.warning("DART 오류: %s", js.get("message"))
                break
            for it in js["list"]:
                if not it.get("stock_code"):
                    continue
                rows.append({
                    "code": it["stock_code"],
                    "published_at": pd.Timestamp(it["rcept_dt"]) + pd.Timedelta(hours=23, minutes=59),
                    "title": it["report_nm"].strip(),
                    "source": "DART",
                })
            if page >= int(js.get("total_page", 1)):
                break
            page += 1
            _time.sleep(self.sleep)
        return pd.DataFrame(rows)
