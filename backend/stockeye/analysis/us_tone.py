"""미국 선물 → 당일단타 '적극 / 보수' (2026-11-02 사용자 제안)

  나스닥·S&P 선물 평균 등락률이 +UP% 이상이면 상승(적극), −DOWN% 이하면 하락(보수), 그 사이는 중립(예전과 동일)
  적극: VWAP 추격 한도 +1%p (일찍·많이 잡음) · 후보 밖 추가 기준 90 → 85점
  보수: 진입 기준 +3점 (80 → 83) · VWAP 추격 한도 −1%p · 후보 상위 5개만 진입
  ⚠ 되돌려 보기에는 과거 미국 선물 분봉이 없어 검증 못 함 (점수를 낮추는 쪽은 되돌려 보기에서 오히려 손실 — 그래서 적극은 점수 기준을 안 낮춤)
     → 신호에 us_tone·us_pct 를 같이 기록해 실전 기록으로 나중에 확인
"""
from __future__ import annotations

UP = 0.5
DOWN = -0.5


def tone_of(fut: dict | None) -> dict:
    """{'tone': '상승'|'하락'|'중립'|None, 'avg': %, 'NQ':…, 'ES':…, 'at':…} — 데이터 없으면 tone None (효과 없음)"""
    if not fut:
        return {"tone": None}
    vals = [fut[k] for k in ("NQ", "ES") if isinstance(fut.get(k), (int, float))]
    if not vals:
        return {"tone": None}
    avg = round(sum(vals) / len(vals), 2)
    tone = "상승" if avg >= UP else ("하락" if avg <= DOWN else "중립")
    return {"tone": tone, "avg": avg, **{k: fut[k] for k in ("NQ", "ES", "at") if k in fut}}


def label(u: dict) -> str:
    if not u.get("tone"):
        return ""
    s = " · ".join(f"{n} {u[k]:+.2f}%" for k, n in (("NQ", "나스닥 선물"), ("ES", "S&P 선물")) if k in u)
    return f"{s} → {'적극 매수' if u['tone'] == '상승' else ('보수적 매수' if u['tone'] == '하락' else '중립')}"
