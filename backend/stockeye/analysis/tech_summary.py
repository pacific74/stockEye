"""종목 상세 '요약 설명' — 보조지표·이평선·거래량·수급·지지/저항으로 지금 차트를 풀어 쓴 규칙 기반 설명

초기 버전처럼 지표를 근거로 설명한다 (V3 점수 설명은 상단 카드에 따로 있음).
  추세: 이평선 배열(5·20·60·120)과 20·60일선 기울기, 20일선 이격
  모멘텀: RSI(14), MACD(시그널 교차·히스토그램 방향), 볼린저 위치, 최근 5·20일 수익률
  거래: 오늘 거래량(20일 평균 대비), 5일 거래량 추세, 상승일/하락일 거래량
  수급: 외국인·기관 5일 순매수
  위치: 52주 고점 대비, 차트 지지·저항(levels) → 매수구간·목표·손절 요약
값이 없으면 그 문장은 건너뛴다. 마지막에 '종합' 한 줄 (지표 점수 → 강세/중립/약세)과 주의를 붙인다.
"""
from __future__ import annotations


def _ok(v) -> bool:
    return v is not None and v == v


def _p(v, nd=1) -> str:
    return f"{'+' if v >= 0 else ''}{v * 100:.{nd}f}%"


def _won(v) -> str:
    return f"{int(v):,}원"


def summarize(x, plan: dict | None = None) -> dict:
    """x: 피처 한 줄(Series/dict), plan: 후보 계획(목표·손절·매수구간) → {'text', 'points', 'tone'}"""
    g = (lambda k: x.get(k)) if hasattr(x, "get") else (lambda k: getattr(x, k, None))
    c = g("close")
    if not _ok(c) or not c:
        return {"text": "지표를 계산할 데이터가 부족합니다.", "points": [], "tone": "중립"}
    pts, sc = [], 0.0

    # ---- 추세 (이평선)
    m = {n: g(f"sma{n}") for n in (5, 20, 60, 120)}
    if all(_ok(m[n]) for n in (5, 20, 60)):
        if m[5] > m[20] > m[60] and (not _ok(m[120]) or m[60] > m[120]):
            t = "이평선 정배열(5>20>60" + (">120" if _ok(m[120]) else "") + ") — 상승 추세"
            sc += 2
        elif m[5] < m[20] < m[60]:
            t = "이평선 역배열(5<20<60) — 하락 추세"
            sc -= 2
        else:
            t = "이평선이 엉켜 있음 — 방향 탐색 구간"
        bits = []
        s20, s60 = g("sma20_slope"), g("sma60_slope")
        if _ok(s20):
            bits.append(f"20일선 {'상승' if s20 > 0.002 else '하락' if s20 < -0.002 else '보합'}({_p(s20, 2)}/5일)")
            sc += 0.5 if s20 > 0 else -0.5
        if _ok(s60):
            bits.append(f"60일선 {'상승' if s60 > 0.002 else '하락' if s60 < -0.002 else '보합'}")
        d20 = c / m[20] - 1
        bits.append(f"주가는 20일선 {'위' if d20 >= 0 else '아래'} {_p(d20)}")
        if d20 > 0.10:
            bits.append("이격이 커 단기 과열")
        pts.append(t + " · " + ", ".join(bits))
    # ---- 모멘텀
    rsi = g("rsi14")
    if _ok(rsi):
        if rsi >= 70:
            pts.append(f"RSI {rsi:.0f} — 과매수 구간, 눌림 가능성")
            sc -= 0.5
        elif rsi <= 30:
            pts.append(f"RSI {rsi:.0f} — 과매도 구간, 기술적 반등 여지")
            sc += 0.3
        else:
            pts.append(f"RSI {rsi:.0f} — {'상승 우위' if rsi >= 55 else '하락 우위' if rsi <= 45 else '중립'}")
            sc += 0.5 if rsi >= 55 else -0.5 if rsi <= 45 else 0
    mh, mhp, mc, ms = g("macd_hist"), g("macd_hist_prev"), g("macd"), g("macd_signal")
    if _ok(mh) and _ok(mc) and _ok(ms):
        cross = ""
        if _ok(mhp) and mhp <= 0 < mh:
            cross, sc = "골든크로스(시그널 상향 돌파) 발생", sc + 1
        elif _ok(mhp) and mhp >= 0 > mh:
            cross, sc = "데드크로스(시그널 하향 이탈) 발생", sc - 1
        else:
            sc += 0.5 if mh > 0 else -0.5
        trend = "" if not _ok(mhp) else (" · 히스토그램 확대" if abs(mh) > abs(mhp) else " · 히스토그램 축소")
        pts.append(f"MACD {'시그널 위' if mh > 0 else '시그널 아래'}" + (f" — {cross}" if cross else "") + trend
                   + (" (0선 위)" if mc > 0 else " (0선 아래)"))
    bp = g("bb_pos")
    if _ok(bp):
        pos = ("상단 돌파" if bp > 1 else "상단 근처" if bp >= 0.8 else "하단 이탈" if bp < 0
               else "하단 근처" if bp <= 0.2 else "중간")
        pts.append(f"볼린저밴드 {pos} (위치 {bp * 100:.0f}%)")
    r5, r20 = g("ret5"), g("ret20")
    if _ok(r5) and _ok(r20):
        pts.append(f"최근 수익률 5일 {_p(r5)} · 20일 {_p(r20)}")
    # ---- 거래량
    vr, v5, ud = g("vol_ratio"), g("vol5_ratio"), g("updown_vol20")
    vb = []
    if _ok(vr):
        vb.append(f"오늘 거래량 20일 평균의 {vr:.1f}배")
    if _ok(v5):
        vb.append(f"최근 5일 {'증가' if v5 >= 1.2 else '감소' if v5 <= 0.8 else '평이'}({v5:.1f}배)")
    if _ok(ud):
        vb.append(f"상승일/하락일 거래량 {ud:.1f}배")
        sc += 0.5 if ud >= 1.2 else -0.5 if ud <= 0.8 else 0
    if vb:
        hint = ""
        if _ok(vr) and vr >= 2 and _ok(g("ret1")):
            hint = " — 대량 거래 동반 " + ("상승" if g("ret1") > 0 else "하락")
            sc += 0.5 if g("ret1") > 0 else -0.5
        pts.append("거래량: " + " · ".join(vb) + hint)
    # ---- 수급
    f5, i5 = g("foreign_net5"), g("institution_net5")
    if _ok(f5) or _ok(i5):
        fb = []
        if _ok(f5):
            fb.append(f"외국인 5일 {'순매수' if f5 > 0 else '순매도'}")
        if _ok(i5):
            fb.append(f"기관 5일 {'순매수' if i5 > 0 else '순매도'}")
        pts.append("수급: " + " · ".join(fb))
        sc += 0.5 * ((_ok(f5) and f5 > 0) + (_ok(i5) and i5 > 0)) - 0.25
    # ---- 위치
    nh = g("near_high250")
    if _ok(nh):
        pts.append(f"52주 최고가 대비 {_p(nh - 1)}" + (" — 신고가 근처" if nh >= 0.97 else ""))
    p = plan or {}
    if p.get("stop") and p.get("target1"):
        sups = [s["label"] for s in (p.get("supports") or [])[:1]]
        ress = [r["label"] for r in (p.get("resistances") or [])[:1]]
        pts.append(f"가까운 지지 {sups[0] if sups else '-'} · 가까운 저항 {ress[0] if ress else '-'}")
    tone = "강세" if sc >= 2.5 else "약세" if sc <= -2 else "중립"
    head = {"강세": "기술적으로 강세 흐름입니다.", "중립": "기술적으로 방향을 탐색하는 중립 구간입니다.",
            "약세": "기술적으로 약세 흐름입니다."}[tone]
    tail = ""
    if p.get("entry_low") and p.get("stop") and p.get("target1"):
        rr = p.get("rr1")
        tail = (f" 매수구간 {_won(p['entry_low'])}~{_won(p['entry_high'])}, 1차 목표 {_won(p['target1'])}, "
                f"손절 {_won(p['stop'])}" + (f" (손익비 1:{rr})" if rr else "") + ".")
    warn = []
    if _ok(rsi) and rsi >= 70:
        warn.append("과매수")
    if _ok(g("atr_pct")) and g("atr_pct") >= 0.06:
        warn.append(f"변동성 큼(하루 평균 {g('atr_pct') * 100:.1f}%)")
    text = head + "\n" + "\n".join("· " + s for s in pts) + ("\n" + tail.strip() if tail else "") + (
        f"\n주의: {', '.join(warn)}." if warn else "")
    return {"text": text, "points": pts, "tone": tone, "score": round(sc, 1)}
