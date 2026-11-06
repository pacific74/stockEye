"""당일단타 '오늘의 후보' — 09:10 에 점수 상위 N개를 고정, 그 뒤 진입은 후보 안에서만 (2026-10-29 사용자 제안)

  되돌려 보기 (20거래일, 전날 거래대금 상위 80종목, 80점 기준): 09:10 점수 순위 상위 5개 → 평균 +0.78% (35건, 손절 37%)
  · 10개 → +0.27% (69건, 손절 54%) · 15개 → −0.10% · 전체 → −0.32% (손절 63%)  — 순위가 높을수록 좋아지는 계단 모양
  ⚠ 한 달 한 장세 · 되돌려 보기엔 수급이 없음 (실전은 호가·뉴스·수급이 더해진 점수로 순위)

  - 09:10 전: 신호가 떠도 '진입 대기' (후보 선별 중)
  - 09:10 뒤 처음 도는 회차에서 점수 상위 N개(진입 금지 제외)를 고정 → system_status 'daytrade'.shortlist 에 저장 (PC 를 껐다 켜도 같은 후보)
  - 후보 밖 종목은 진입 조건이 맞아도 '진입 대기' — 단, LATE_ADD 점 이상이면 후보로 추가 (⚠ 검증 안 된 값)
  - 미국 선물(analysis/us_tone.py): 하락(보수)이면 후보 상위 TOP_DOWN 개만 진입 · 상승(적극)이면 후보 밖 추가 기준 LATE_ADD_UP 점
  - TYPES: 진입 유형 제한 — 지금은 눌림목형만 (None 이면 돌파·눌림목 둘 다). 돌파형은 신호가 떠도 '진입 대기'
"""
from __future__ import annotations

EARLY_AT = "09:00"        # 2026-11-05 사용자: 10분 지켜보고 뽑으면 늦다 → 09:00 에 NXT 프리마켓 등으로 후보풀을 넓혀 5종목 먼저
FREEZE_AT = "09:05"       # 09:05 에 그때 점수 상위 5개를 더해 총 10종목 확정 (예전엔 09:10 에 상위 10개)
EARLY_N = 5
EARLY_MIN, EARLY_MAX = 3.0, 25.0   # 프리마켓 등락 범위 (%) — 너무 큰 갭(상한가 근처)은 진입 불가
EARLY_MIN_PV = 3e9        # 전일 거래대금 30억 이상
EARLY_BOOST = 5.0         # 급등예상 목록(점수 상위 100)에도 있으면 가산
N = 10                    # 오늘의 후보 개수
TOP = 5                   # 그중 우선 (되돌려 보기에서 가장 좋았던 구간)
LATE_ADD = 90.0           # 후보 밖이라도 이 점수 이상이면 추가 (검증 안 된 초기값)
LATE_ADD_UP = 85.0        # 미국 선물 상승(적극)이면 후보 밖 추가 기준을 90 → 85점 (검증 안 됨)
TOP_DOWN = 5              # 미국 선물 하락(보수)이면 후보 상위 5개만 진입 (되돌려 보기: 상위 5개가 가장 좋았음)
TYPES: tuple[str, ...] | None = None   # 2026-10-29: 후보 안에서도 눌림목형이 앞섰음 (상위 10개: 눌림목 +0.81% 27건 · 돌파 −0.07% 42건) → 눌림목만


def new_state() -> dict:
    return {"at": None, "list": [], "late": [], "early": []}


def frozen(st: dict) -> bool:
    return bool(st.get("at"))


def pick(res: list[dict], n: int = N) -> list[dict]:
    """진입 금지(제외 사유) 아닌 종목 중 점수 상위 n개"""
    ok = [r for r in res if not r.get("excluded") and r.get("code")]
    ok.sort(key=lambda r: -float(r.get("score") or 0))
    return [{"code": r["code"], "name": r.get("name"), "score": round(float(r.get("score") or 0), 1),
             "type": r.get("type"), "rank": i} for i, r in enumerate(ok[:n], 1)]


TIERS = ((EARLY_MIN, EARLY_MIN_PV, None), (1.5, 1e9, 0.03), (0.5, 5e8, 0.0))   # 5개가 안 모이면 기준을 단계적으로 풀어 채움


def early_pick(pre: dict, info: dict, boost: set | None = None, n: int = EARLY_N, after: dict | None = None,
               flow: dict | None = None, live: dict | None = None) -> list[dict]:
    """09:00 선발 — 프리마켓(pre) · 어제 저녁 애프터마켓(after) = {코드: [가격, 종가 대비 %]} · 09:00 시초 등락(live = {코드: %}) 중
    하나라도 +EARLY_MIN~MAX% 인 종목 (애프터는 프리마켓이 0% 이상일 때만). info[code] = {adr, pv(전일 거래대금), name}.
    평소 변동폭(MIN_ADR)·전일 거래대금을 거른 뒤 점수 순으로 n개. 모자라면 TIERS 순서로 기준을 풀어 n개를 채움.
    점수 = max(프리마켓, 시초 등락) + 0.5×애프터마켓 + 급등예상 가산 + 외국인·기관 3일 순매수 가산(최대 5)  (⚠ 가중치는 검증 전 초기값)"""
    from ..engine.daytrade import MIN_ADR
    boost, after, flow, live = boost or set(), after or {}, flow or {}, live or {}
    out: list[dict] = []
    have: set[str] = set()
    for lo, min_pv, adr_min in TIERS:
        rows = []
        for c in set(pre) | set(after) | set(live):
            i = info.get(c)
            if c in have or not i:
                continue
            pv = (pre.get(c) or [None, None])[1]
            av = (after.get(c) or [None, None])[1]
            lv = live.get(c)
            ok_pre = pv is not None and lo <= pv <= EARLY_MAX
            ok_live = lv is not None and lo <= lv <= EARLY_MAX
            ok_aft = av is not None and lo <= av <= EARLY_MAX and (pv is None or pv >= 0)
            if not (ok_pre or ok_live or ok_aft):
                continue
            if (i.get("adr") or 0) < (MIN_ADR if adr_min is None else adr_min) or (i.get("pv") or 0) < min_pv:
                continue
            fb = min(max(float(flow.get(c) or 0) * 100, 0.0), 5.0)
            top = max([x for x in (pv, lv) if x is not None] or [0.0])
            rows.append({"code": c, "name": i.get("name") or c, "pre": None if pv is None else round(float(pv), 2),
                         "after": None if av is None else round(float(av), 2), "open": None if lv is None else round(float(lv), 2),
                         "adr": round(float(i["adr"]) * 100, 1), "pv_eok": round(float(i["pv"]) / 1e8),
                         "surge": c in boost, "flow": round(fb, 1), "tier": TIERS.index((lo, min_pv, adr_min)) + 1,
                         "key": float(top) + 0.5 * float(av or 0) + (EARLY_BOOST if c in boost else 0) + fb})
        rows.sort(key=lambda r: -r["key"])
        for r in rows[: n - len(out)]:
            r["score"] = round(r.pop("key"), 1)
            out.append(r)
            have.add(r["code"])
        if len(out) >= n:
            break
    return out


def freeze(st: dict, res: list[dict], hm: str) -> bool:
    """FREEZE_AT 뒤 처음 호출에서 후보 고정 = 09:00 선발(early) + 그때 점수 상위 (N − 선발)개. 이미 고정이면 False
    순위는 점수 순 (선발 종목이 아직 점수가 없으면 맨 뒤)"""
    if frozen(st) or hm < FREEZE_AT:
        return False
    byc = {r["code"]: r for r in res if r.get("code")}
    early = [x["code"] for x in st.get("early") or []]
    rows = []
    for x in st.get("early") or []:
        r = byc.get(x["code"])
        rows.append({"code": x["code"], "name": x.get("name"), "score": round(float((r or {}).get("score") or 0), 1),
                     "type": (r or {}).get("type"), "src": "early", "pre": x.get("pre"), "after": x.get("after")})
    rest = pick([r for r in res if r.get("code") not in early], max(N - len(rows), 0))
    rows += [{**x, "src": "score"} for x in rest]
    rows.sort(key=lambda r: -float(r.get("score") or 0))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    st["at"], st["list"], st["late"] = hm, rows, []
    return True


def rank_of(st: dict, code: str) -> int | None:
    for x in st.get("list") or []:
        if x["code"] == code:
            return int(x["rank"])
    return None


def gate(r: dict, st: dict, tone: str | None = None) -> None:
    """'진입 조건 충족' 이면 후보 안인지 확인 → 아니면 '진입 대기' 로 내리고 이유를 경고에 적음"""
    if r.get("status") != "진입 조건 충족":
        return
    code = r.get("code")
    why = None
    if not frozen(st):
        why = f"{FREEZE_AT} 에 오늘의 후보 {N}개를 고른 뒤 진입 (후보 선별 중)"
    elif rank_of(st, code) is None and code not in (st.get("late") or []):
        if float(r.get("score") or 0) >= (LATE_ADD_UP if tone == "상승" else LATE_ADD):
            st.setdefault("late", []).append(code)
        else:
            why = f"오늘의 후보 {N}개 밖 (후보 밖 진입은 되돌려 보기에서 손실이 컸음)"
    if why is None and tone == "하락":
        rk = rank_of(st, code)
        if rk is not None and rk > TOP_DOWN:
            why = f"미국 선물 하락 — 후보 상위 {TOP_DOWN}개만 진입 (보수적)"
    if why is None and TYPES and r.get("type") not in TYPES:
        why = f"{'·'.join(TYPES)}만 진입 ({r.get('type')} 제외)"
    if why:
        r["status"] = "진입 대기"
        r.setdefault("warnings", []).append(why)


def tag(r: dict, st: dict) -> None:
    """앱 표시용: 후보 순위 (후보 밖 추가분은 0) · 09:00 선발 종목이면 early + 근거(프리·애프터 %)"""
    code = r.get("code")
    rk = rank_of(st, code)
    ex = next((x for x in st.get("list") or [] if x["code"] == code and x.get("src") == "early"), None) \
        or next((x for x in st.get("early") or [] if x["code"] == code), None)
    if ex:
        r["early"] = True
        r["early_info"] = {"pre": ex.get("pre"), "after": ex.get("after")}
    if rk is not None:
        r["cand_rank"] = rk
    elif ex or code in (st.get("late") or []):
        r["cand_rank"] = 0


def view(st: dict) -> dict:
    return {"at": st.get("at"), "n": N, "top": TOP, "list": st.get("list") or [], "late": st.get("late") or [], "early": st.get("early") or [], "early_at": EARLY_AT, "early_n": EARLY_N,
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
        if str(p.get("date")) == day and s.get("early"):
            st["early"] = list(s["early"])
    except Exception:  # noqa: BLE001
        pass
    return st
