"""종목 상세 '요약 설명' — 보조지표·이평선·거래량·수급·지지/저항으로 지금 차트를 풀어 쓴 규칙 기반 설명

초기 버전처럼 지표를 근거로 설명한다 (V3 점수 설명은 상단 카드에 따로 있음).
  추세: 이평선 배열(5·20·60·120)과 20·60일선 기울기, 20일선 이격
  모멘텀: RSI(14), MACD(시그널 교차·히스토그램 방향), 볼린저 위치, 최근 5·20일 수익률
  거래: 오늘 거래량(20일 평균 대비), 5일 거래량 추세, 상승일/하락일 거래량
  수급: 외국인·기관 5일 순매수
  위치: 52주 고점 대비, 차트 지지·저항(levels) → 매수구간·목표·손절 요약
값이 없으면 그 문장은 건너뛴다. 숫자를 나열하지 않고 사람이 말하듯 문단으로 풀어 쓴다. 투자에 중요한 부분은 **굵게** (앱이 강조 표시).
첫 문장은 종합(지표 점수 → 강세/중립/약세), 마지막에 주의할 점.
"""
from __future__ import annotations


def _ok(v) -> bool:
    return v is not None and v == v


def _p(v, nd=1) -> str:
    return f"{'+' if v >= 0 else ''}{v * 100:.{nd}f}%"


def _won(v) -> str:
    return f"{int(v):,}원"


def _eok(v) -> str:
    """원 → '약 12억 원' / '약 3,400만 원'"""
    a = abs(v)
    if a >= 1e8:
        return f"약 {a / 1e8:,.0f}억 원"
    return f"약 {a / 1e4:,.0f}만 원"


def summarize(x, plan: dict | None = None) -> dict:
    """x: 피처 한 줄(Series/dict), plan: 후보 계획(목표·손절·매수구간) → {'text', 'points', 'tone'}
    숫자를 나열하지 않고 문장으로 풀어 쓴다 (흐름 → 힘 → 거래·수급 → 위치·계획 → 주의)."""
    g = (lambda k: x.get(k)) if hasattr(x, "get") else (lambda k: getattr(x, k, None))
    c = g("close")
    if not _ok(c) or not c:
        return {"text": "지표를 계산할 데이터가 부족합니다.", "points": [], "tone": "중립"}
    paras, sc = [], 0.0

    # ---- ① 흐름 (이평선)
    m = {n: g(f"sma{n}") for n in (5, 20, 60, 120)}
    flow = []
    if all(_ok(m[n]) for n in (5, 20, 60)):
        s20, s60 = g("sma20_slope"), g("sma60_slope")
        if m[5] > m[20] > m[60] and (not _ok(m[120]) or m[60] > m[120]):
            flow.append("이평선들이 짧은 것부터 차례로 위에 놓인 **정배열이라 상승 추세**에 있고")
            sc += 2
        elif m[5] < m[20] < m[60]:
            flow.append("이평선들이 **역배열로 놓여 하락 추세**가 이어지고 있고")
            sc -= 2
        else:
            flow.append("이평선들이 서로 엉켜 있어 아직 방향을 정하지 못한 모습이고")
        if _ok(s20):
            sc += 0.5 if s20 > 0 else -0.5
            if s20 > 0.002:
                flow.append(f"20일선도 최근 5일 동안 {s20 * 100:.1f}% 올라 꾸준히 오르는 중입니다")
            elif s20 < -0.002:
                flow.append(f"20일선은 최근 5일 동안 {abs(s20) * 100:.1f}% 내려 아직 내림세입니다")
            else:
                flow.append("20일선은 옆으로 평평하게 가고 있습니다")
        mid = ""
        if _ok(s60) and abs(s60) > 0.002:
            mid = (" 60일선도 오르고 있어 중기 흐름이 받쳐 줍니다." if s60 > 0
                   else (" 다만" if sc > 0 else "") + " 60일선도 내리고 있어 중기 흐름은 부담입니다.")
        d20 = c / m[20] - 1
        if d20 > 0.10:
            tail = f"주가가 20일선보다 {d20 * 100:.0f}%나 위에 있어 **단기로는 많이 오른 상태**입니다"
        elif d20 >= 0:
            tail = f"주가는 20일선보다 {d20 * 100:.1f}% 위에 있어 크게 벌어지지 않았습니다"
        elif d20 > -0.05:
            tail = f"주가는 20일선 바로 아래({d20 * 100:.1f}%)에 있어 **20일선 회복 여부가 관건**입니다"
        else:
            tail = f"주가가 20일선보다 {abs(d20) * 100:.0f}% 아래로 처져 있습니다"
        paras.append(", ".join(flow) + "." + mid + " " + tail + ".")

    # ---- ② 힘 (RSI · MACD · 볼린저 · 수익률)
    mom = []
    rsi = g("rsi14")
    if _ok(rsi):
        if rsi >= 70:
            mom.append(f"RSI가 {rsi:.0f}로 **과열권**이라 잠시 쉬어 갈 수 있고")
            sc -= 0.5
        elif rsi <= 30:
            mom.append(f"RSI가 {rsi:.0f}로 많이 눌려 있어 **기술적 반등 여지**가 있고")
            sc += 0.3
        elif rsi >= 55:
            mom.append(f"RSI가 {rsi:.0f}로 사려는 힘이 조금 앞서고")
            sc += 0.5
        elif rsi <= 45:
            mom.append(f"RSI가 {rsi:.0f}로 팔려는 힘이 조금 앞서고")
            sc -= 0.5
        else:
            mom.append(f"RSI는 {rsi:.0f}로 사고파는 힘이 비슷하고")
    mh, mhp, mc = g("macd_hist"), g("macd_hist_prev"), g("macd")
    if _ok(mh) and _ok(mc):
        if _ok(mhp) and mhp <= 0 < mh:
            mom.append("MACD가 막 시그널선을 위로 뚫는 **골든크로스**가 나와 상승 신호가 켜졌습니다")
            sc += 1
        elif _ok(mhp) and mhp >= 0 > mh:
            mom.append("MACD가 막 시그널선 아래로 내려오는 **데드크로스**가 나와 상승 힘이 꺾이는 신호입니다")
            sc -= 1
        elif mh > 0:
            mom.append("MACD는 시그널선 위에서 " + ("힘이 더 붙는 중입니다" if _ok(mhp) and abs(mh) > abs(mhp)
                                                   else "유지되지만 힘은 조금 줄고 있습니다"))
            sc += 0.5
        else:
            mom.append("MACD는 시그널선 아래라 " + ("하락 힘이 커지는 중입니다" if _ok(mhp) and abs(mh) > abs(mhp)
                                                  else "아직 약하지만 하락 힘은 줄어드는 중입니다")
                       + (" (그래도 0선 위)" if mc > 0 else ""))
            sc -= 0.5
    if mom:
        mom = [", ".join(mom) + "."]
    bp = g("bb_pos")
    r5, r20 = g("ret5"), g("ret20")
    tail = []
    if _ok(bp):
        tail.append("볼린저밴드에서는 " + ("위쪽 끝을 넘어선 강한 자리" if bp > 1 else "윗부분" if bp >= 0.8
                                         else "아래쪽 끝을 벗어난 약한 자리" if bp < 0 else "아랫부분" if bp <= 0.2
                                         else "가운데쯤") + "에 있고")
    if _ok(r5) and _ok(r20):
        a5, a20 = abs(r5) * 100, abs(r20) * 100
        if (r5 >= 0) == (r20 >= 0):
            tail.append(f"최근 5일 {a5:.1f}%, 20일로 보면 {a20:.1f}% {'올랐습니다' if r5 >= 0 else '내렸습니다'}")
        else:
            tail.append(f"최근 5일은 {a5:.1f}% {'올랐' if r5 >= 0 else '내렸'}지만 20일로 보면 {a20:.1f}% {'올랐습니다' if r20 >= 0 else '내렸습니다'}")
    elif tail:
        tail[-1] = tail[-1][:-1] + "습니다"
    if tail:
        mom.append(", ".join(tail) + ".")
    if mom:
        paras.append(" ".join(mom))

    # ---- ③ 거래량 · 수급
    vr, v5, ud = g("vol_ratio"), g("vol5_ratio"), g("updown_vol20")
    a = None                                                    # 오늘 거래
    if _ok(vr):
        r1 = g("ret1")
        if vr >= 2:
            a = f"오늘 **거래량이 평소의 {vr:.1f}배**로 크게 늘며 " + ("올라 **매수세가 몰렸**" if _ok(r1) and r1 > 0 else "내려 **매도 물량이 나왔**")
            sc += 0.5 if _ok(r1) and r1 > 0 else -0.5
        elif vr <= 0.6:
            a = "오늘 거래는 평소보다 한산했"
        else:
            a = "오늘 거래량은 평소와 비슷했"
    b = None                                                    # 최근 5일 거래
    if _ok(v5):
        b = "최근 5일 거래는 " + ("늘어나는 중입니다" if v5 >= 1.2 else "줄어드는 중입니다" if v5 <= 0.8 else "평소 수준입니다")
    sent = ""
    if a and b:
        sent = a + "고, " + b + "."
    elif a:
        sent = a + "습니다."
    elif b:
        sent = b + "."
    if _ok(ud):
        sc += 0.5 if ud >= 1.2 else -0.5 if ud <= 0.8 else 0
        if ud >= 1.2:
            sent += " 오른 날 거래가 더 많아 사려는 쪽이 우세합니다."
        elif ud <= 0.8:
            sent += " 내린 날 거래가 더 많아 파는 쪽이 우세합니다."
    f5, i5 = g("foreign_net5"), g("institution_net5")
    v5d = g("value_ma5")

    def who(name, v):
        share = f"(5일 거래대금의 {abs(v) / (v5d * 5) * 100:.0f}%)" if _ok(v5d) and v5d else ""
        return f"{name}은 최근 5일 {_eok(v)}{share}어치를 {'사들였' if v > 0 else '팔았'}"
    fl = []
    if _ok(f5) and f5:
        fl.append(who("외국인", f5))
    if _ok(i5) and i5:
        fl.append(who("기관", i5))
    if fl:
        sc += 0.5 * ((_ok(f5) and f5 > 0) + (_ok(i5) and i5 > 0)) - 0.25
        sent += " " + "고, ".join(fl) + "습니다."
        if len(fl) == 2 and (f5 > 0) == (i5 > 0):
            sent += f" **외국인과 기관이 함께 {'사고' if f5 > 0 else '팔고'} 있습니다.**"
    if sent.strip():
        paras.append(sent.strip())

    # ---- ④ 위치 · 계획
    pos = []
    nh = g("near_high250")
    if _ok(nh):
        pos.append("**52주 최고가 근처**까지 올라와 있습니다" if nh >= 0.97 else f"52주 최고가보다 {(1 - nh) * 100:.0f}% 아래에 있습니다")
    p = plan or {}
    sups = [s["label"] for s in (p.get("supports") or [])[:1]]
    ress = [r["label"] for r in (p.get("resistances") or [])[:1]]
    if sups or ress:
        pos.append("가까운 지지는 " + (sups[0] if sups else "뚜렷하지 않고") + (", 저항은 " + ress[0] if ress else "") + "입니다")
    if p.get("entry_low") and p.get("stop") and p.get("target1"):
        rr = p.get("rr1") or p.get("rr")
        pos.append(f"매수구간은 **{_won(p['entry_low'])}~{_won(p['entry_high'])}**, 1차 목표 **{_won(p['target1'])}**, "
                   f"손절 **{_won(p['stop'])}**" + (f"(손익비 1:{rr})" if rr else "") + "입니다")
    if pos:
        paras.append(" ".join(x + "." for x in pos))

    tone = "강세" if sc >= 2.5 else "약세" if sc <= -2 else "중립"
    head = {"강세": "**기술적으로 강세 흐름입니다.**", "중립": "**기술적으로 방향을 탐색하는 중립 구간입니다.**",
            "약세": "**기술적으로 약세 흐름입니다.**"}[tone]
    warn = []
    if _ok(rsi) and rsi >= 70:
        warn.append("단기 과열")
    if _ok(g("atr_pct")) and g("atr_pct") >= 0.06:
        warn.append(f"하루 평균 {g('atr_pct') * 100:.1f}%씩 움직일 만큼 변동성이 큼")
    text = head + " " + "\n".join(paras) + (f"\n**주의할 점: {', '.join(warn)}.**" if warn else "")
    return {"text": text, "points": paras, "tone": tone, "score": round(sc, 1)}
