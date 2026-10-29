"""당일단타 '오늘의 후보' — 09:10 에 점수 상위 N개를 고정, 그 뒤 진입은 후보 안에서만 (2026-10-29 사용자 제안)

  되돌려 보기 (20거래일, 전날 거래대금 상위 80종목, 80점 기준): 09:10 점수 순위 상위 5개 → 평균 +0.78% (35건, 손절 37%)
  · 10개 → +0.27% (69건, 손절 54%) · 15개 → −0.10% · 전체 → −0.32% (손절 63%)  — 순위가 높을수록 좋아지는 계단 모양
  ⚠ 한 달 한 장세 · 되돌려 보기엔 수급이 없음 (실전은 호가·뉴스·수급이 더해진 점수로 순위)

  - 09:10 전: 신호가 떠도 '진입 대기' (후보 선별 중)
  - 09:10 뒤 처음 도는 회차에서 점수 상위 N개(진입 금지 제외)를 고정 → system_status 'daytrade'.shortlist 에 저장 (PC 를 껐다 켜도 같은 후보)
  - 후보 밖 종목은 진입 조건이 맞아도 '진입 대기' — 단, LATE_ADD 점 이상이면 후보로 추가 (⚠ 검증 안 된 값)
  - TYPES 로 유형 제한 가능 (예: ('눌림목',)) — 기본은 돌파·눌림목 둘 다
"""
from __future__ import annotations

FREEZE_AT = "09:10"
N = 10                    # 오늘의 후보 개수
TOP = 5                   # 그중 우선 (되돌려 보기에서 가장 좋았던 구간)
LATE_ADD = 90.0           # 후보 밖이라도 이 점수 이상이면 추가 (검증 안 된 초기값)
TYPES: tuple[str, ...] | None = None


def new_state() -> dict:
    return {"at": None, "list": [], "late": []}


def frozen(st: dict) -> bool:
    return bool(st.get("at"))


def pick(res: list[dict], n: int = N) -> list[dict]:
    """진입 금지(제외 사유) 아닌 종목 중 점수 상위 n개"""
    ok = [r for r in res if not r.get("excluded") and r.get("code")]
    ok.sort(key=lambda r: -float(r.get("score") or 0))
    return [{"code": r["code"], "name": r.get("name"), "score": round(float(r.get("score") or 0), 1),
             "type": r.get("type"), "rank": i} for i, r in enumerate(ok[:n], 1)]


def freeze(st: dict, res: list[dict], hm: str) -> bool:
    """09:10 뒤 처음 호출에서 후보 고정. 이미 고정이면 False"""
    if frozen(st) or hm < FREEZE_AT:
        return False
    st["at"], st["list"], st["late"] = hm, pick(res), []
    return True


def rank_of(st: dict, code: str) -> int | None:
    for x in st.get("list") or []:
        if x["code"] == code:
            return int(x["rank"])
    return None


def gate(r: dict, st: dict) -> None:
    """'진입 조건 충족' 이면 후보 안인지 확인 → 아니면 '진입 대기' 로 내리고 이유를 경고에 적음"""
    if r.get("status") != "진입 조건 충족":
        return
    code = r.get("code")
    why = None
    if not frozen(st):
        why = f"{FREEZE_AT} 에 오늘의 후보 {N}개를 고른 뒤 진입 (후보 선별 중)"
    elif rank_of(st, code) is None and code not in (st.get("late") or []):
        if float(r.get("score") or 0) >= LATE_ADD:
            st.setdefault("late", []).append(code)
        else:
            why = f"오늘의 후보 {N}개 밖 (후보 밖 진입은 되돌려 보기에서 손실이 컸음)"
    if why is None and TYPES and r.get("type") not in TYPES:
        why = f"{'·'.join(TYPES)}만 진입 ({r.get('type')} 제외)"
    if why:
        r["status"] = "진입 대기"
        r.setdefault("warnings", []).append(why)


def tag(r: dict, st: dict) -> None:
    """앱 표시용: 후보 순위 (후보 밖 추가분은 0)"""
    rk = rank_of(st, r.get("code"))
    if rk is not None:
        r["cand_rank"] = rk
    elif r.get("code") in (st.get("late") or []):
        r["cand_rank"] = 0


def view(st: dict) -> dict:
    return {"at": st.get("at"), "n": N, "top": TOP, "list": st.get("list") or [], "late": st.get("late") or [],
            "state": "확정" if frozen(st) else "선별 중", "freeze_at": FREEZE_AT}


def restore(sb, day: str) -> dict:
    """PC 를 껐다 켠 경우: 오늘 발행된 후보를 그대로"""
    st = new_state()
    if not sb:
        return st
    try:
        rows = sb.select("system_status", {"select": "payload", "key": "eq.daytrade"})
        p = (rows[0].get("payload") if rows else None) or {}
        s = p.get("shortlist") or {}
        if str(p.get("date")) == day and s.get("at") and s.get("list"):
            st.update({"at": s["at"], "list": s["list"], "late": list(s.get("late") or [])})
    except Exception:  # noqa: BLE001
        pass
    return st
