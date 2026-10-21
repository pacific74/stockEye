"""장중 재분석에서 '당일 추천' 표시 — 전날 저녁 목록에 없다가 오늘 장중에 새로 들어온 후보에 c["today_new"] = True

  기준(전날 저녁 목록) = reports/latest.json 의 후보 중 today_new 가 아닌 것.
  최근 발행본이 앞선 장중 재분석(11:00)이어도 그 안의 today_new 후보는 기준에 넣지 않으므로
  14:00 에도 11:00 에 새로 들어온 종목에 계속 표시된다. 저녁 배치는 새로 만들어 표시가 없어진다.
  앱은 점수 옆에 [당일] 을 보여 준다.
"""
from __future__ import annotations


def _lists(report: dict) -> dict[str, list]:
    out = {"_main": report.get("candidates") or []}
    for k, v in (report.get("strategies") or {}).items():
        out[k] = (v or {}).get("candidates") or []
    return out


def mark(report: dict, prev: dict | None) -> int:
    """report 의 후보에 today_new 표시 (없으면 키 삭제). 새로 표시된 개수 반환. prev 가 없으면 아무것도 안 함"""
    if not prev:
        return 0
    base = {k: {c.get("code") for c in cs if not c.get("today_new")} for k, cs in _lists(prev).items()}
    n = 0
    for k, cs in _lists(report).items():
        if k not in base:                     # 어제 저녁에 없던 탭이면 전부 새것이 되니 표시하지 않음
            continue
        for c in cs:
            if c.get("code") not in base[k]:
                c["today_new"] = True
                n += 1
            else:
                c.pop("today_new", None)
    return n
