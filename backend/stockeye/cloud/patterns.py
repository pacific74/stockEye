"""종목 검색 → '비슷한 과거 패턴' 요청 처리

앱에서 패턴이 아직 없는 종목을 열고 [패턴 찾기 요청]을 누르면 pattern_requests 에 한 줄이 들어간다.
  - Supabase 가 GitHub 에 바로 신호를 보내면 (선택 설정) patterns 작업이 몇 분 안에 실행
  - 신호 설정이 없어도 매시간 점검 · 장중 재분석(11시·14시) · 저녁 배치 끝에서 같이 처리
결과는 stock_details.similar_patterns 에 넣어서, 같은 종목은 다른 회원도 바로 본다.
요청했던 종목은 며칠 동안 저녁 배치에서 계속 새로 계산한다 (recent_requested).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd

log = logging.getLogger(__name__)
TABLE = "pattern_requests"


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def recent_requested(sb, days: int = 5) -> list[str]:
    """최근 며칠 동안 회원이 요청했던 종목 (저녁 배치에서 계속 갱신)"""
    since = (datetime.utcnow() - timedelta(days=days)).isoformat() + "Z"
    try:
        rows = sb.select(TABLE, {"select": "code", "created_at": f"gte.{since}", "limit": "500"})
    except Exception as e:  # noqa: BLE001  (표가 아직 없으면 생략)
        log.info("패턴 요청 목록 생략: %s", e)
        return []
    return sorted({r["code"] for r in rows if r.get("code")})


def process_pattern_requests(sb, pit, limit: int = 60, pi=None, as_of=None) -> int:
    """대기 중인 요청을 한 번에 처리 → stock_details.similar_patterns 갱신. 처리한 요청 수를 돌려줌"""
    try:
        reqs = sb.select(TABLE, {"status": "eq.queued", "order": "id.asc", "limit": str(limit)})
    except Exception as e:  # noqa: BLE001
        log.info("패턴 요청 표 없음/조회 실패 → 생략: %s", e)
        return 0
    if not reqs:
        return 0
    ids = ",".join(str(r["id"]) for r in reqs)
    sb.update(TABLE, {"id": f"in.({ids})"}, {"status": "running"})
    codes = list(dict.fromkeys(r["code"] for r in reqs))
    log.info("패턴 요청 %d건 (%d종목) 처리", len(reqs), len(codes))
    from ..analysis.similar import PatternIndex
    from ..details import similar_payloads
    date = pd.Timestamp(as_of) if as_of is not None else pit.ohlcv["date"].max()
    if pi is None:
        pi = PatternIndex(pit.ohlcv, window=20)
    lst = pit.listing if not pit.listing.empty else pd.DataFrame(columns=["code", "name"])
    name_of = dict(zip(lst["code"], lst["name"]))
    try:
        results = similar_payloads(pi, codes, date, pit.ohlcv, name_of)
    except Exception as e:  # noqa: BLE001
        sb.update(TABLE, {"id": f"in.({ids})"}, {"status": "failed", "message": str(e)[:300], "done_at": _now()})
        raise
    status = {}
    for code, s in results.items():
        if "error" in s:
            status[code] = ("failed", s["error"])
            continue
        upd = sb.update("stock_details", {"code": f"eq.{code}"}, {"similar_patterns": s}, returning=True)
        status[code] = ("done", None) if upd else ("failed", "종목 상세가 아직 없음 (상장 직후·데이터 부족)")
    for r in reqs:
        st, msg = status.get(r["code"], ("failed", "처리 안 됨"))
        sb.update(TABLE, {"id": f"eq.{r['id']}"}, {"status": st, "message": msg, "done_at": _now()})
    return len(reqs)
