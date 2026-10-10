"""저녁 리포트 알림 (ntfy·텔레그램)

  📊 10/9(금) 장마감 리포트
  ■ 금일장 브리핑     — 지수 등락·이평선 위치, 상승/하락 종목, 거래대금, 강한 업종
  ■ 내일장 예상       — 지표 점수(추세·종목 확산·마감 강도·후보 수)로 우호/중립/경계 + 확인할 지수 가격
  ■ 내일 관심주       — 후보 메뉴 탭별 상위 3: 종목명(코드) 점수 · 현재가 · 목표 · 손절

알림 길이: ntfy 본문은 4,096바이트(한글 약 1,300자)를 넘으면 첨부파일로 바뀌므로 3,900바이트 안으로 줄인다.
텔레그램은 4,096자까지라 같은 본문이면 충분하다.
'내일장 예상'은 지표를 정리한 참고 문장이며 예측이 아니다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MAX_BYTES = 3900
TAB_ORDER = ["v3", "nextday", "early", "reversal", "uplimit"]       # 앱 후보 메뉴 순서 (새 탭은 뒤에 자동으로)
WEEK = "월화수목금토일"
IDX_NAME = {"KOSPI": "코스피", "KOSDAQ": "코스닥"}
TAB_LABEL = {"v3": "V3", "nextday": "익일유망주", "early": "상승초기", "reversal": "추세전환", "uplimit": "상파"}   # 앱 관심 탭 이름


# ---------------------------------------------------------------- 리포트 만들 때: 지수·시장 요약 숫자
def market_brief(index_df: pd.DataFrame, ohlcv: pd.DataFrame | None = None) -> dict:
    """지수별 등락·이평선·20일 고점 거리 + 시장 전체 거래대금 변화 (선정일 종가까지만 사용)"""
    out = {"indices": []}
    for code in ("KOSPI", "KOSDAQ"):
        s = index_df[index_df["code"] == code].sort_values("date")["close"].astype(float) if len(index_df) else pd.Series()
        if len(s) < 61:
            continue
        c = s.iloc[-1]
        ma = {n: s.rolling(n).mean() for n in (5, 20, 60)}
        out["indices"].append({
            "code": code, "name": IDX_NAME.get(code, code), "close": round(c, 2),
            "chg1": round((c / s.iloc[-2] - 1) * 100, 2), "chg5": round((c / s.iloc[-6] - 1) * 100, 2),
            "ma5": round(ma[5].iloc[-1], 2), "ma20": round(ma[20].iloc[-1], 2), "ma60": round(ma[60].iloc[-1], 2),
            "ma20_slope": round((ma[20].iloc[-1] / ma[20].iloc[-6] - 1) * 100, 2),
            "ma60_slope": round((ma[60].iloc[-1] / ma[60].iloc[-11] - 1) * 100, 2),
            "from_high20": round((c / s.tail(20).max() - 1) * 100, 2),
            "streak": _streak(s),
        })
    if ohlcv is not None and len(ohlcv) and "value" in ohlcv:
        tv = ohlcv.groupby("date")["value"].sum().sort_index().tail(21)
        if len(tv) >= 21 and tv.iloc[:-1].mean() > 0:
            out["value_today"] = round(float(tv.iloc[-1]) / 1e12, 1)                 # 조원
            out["value_ratio"] = round(float(tv.iloc[-1] / tv.iloc[:-1].mean()), 2)
    return out


def _streak(s: pd.Series) -> int:
    """연속 상승(+)/하락(-) 일수"""
    d = np.sign(s.diff().dropna().to_numpy()[::-1])
    if not len(d) or d[0] == 0:
        return 0
    n = int(np.argmax(d != d[0])) if (d != d[0]).any() else len(d)
    return int(n * d[0])


# ---------------------------------------------------------------- 알림 문장
def _md(date: str) -> str:
    t = pd.Timestamp(date)
    return f"{t.month}/{t.day}({WEEK[t.weekday()]})"


def _won(v) -> str:
    return "-" if v is None or v != v or not v else f"{int(round(float(v))):,}"


def _pct(v, nd=1) -> str:
    return "-" if v is None or v != v else f"{'+' if v >= 0 else ''}{float(v):.{nd}f}%"


BR = "  "          # Markdown 줄바꿈 (줄 끝 공백 두 칸) — 한 항목을 맥락에 맞춰 2줄로 나눌 때
IND = "   "         # 목록 항목 아래 둘째 줄 들여쓰기


def today_brief(report: dict) -> list[str]:
    """금일장 브리핑 (Markdown 목록, 긴 항목은 맥락 단위로 2줄)"""
    m = report.get("market") or {}
    b = report.get("brief") or {}
    lines = []
    for i in b.get("indices", []):
        pos = " · ".join(f"{n}일선 {'위' if i['close'] >= i[f'ma{n}'] else '아래'}" for n in (20, 60))
        st = i.get("streak") or 0
        tail = f" · {abs(st)}일 연속 {'상승' if st > 0 else '하락'}" if abs(st) >= 3 else ""
        lines.append(f"- **{i['name']}** {i['close']:,.2f} ({_pct(i['chg1'], 2)}, 5일 {_pct(i['chg5'])}){BR}")
        lines.append(f"{IND}{pos}{tail}")
    if not lines:                                   # 예전 리포트
        for i in m.get("indices", []):
            lines.append(f"- **{IDX_NAME.get(i['code'], i['code'])}** {i['close']:,.2f} ({_pct(i['change_pct'], 2)})")
    adv, dec = m.get("advancers"), m.get("decliners")
    if adv is not None:
        first = f"상승 {adv:,} · 하락 {dec:,}" + (f" · 상한가 {m['limit_up']}" if m.get("limit_up") else "")
        second = (f"거래대금 {b['value_today']}조 (20일 평균의 {b['value_ratio']:.1f}배) · " if b.get("value_today") else "") \
            + f"{m.get('mood_icon', '')} **{m.get('mood', '')}**"
        lines.append(f"- {first}{BR}")
        lines.append(f"{IND}{second}")
    sec = [s for s in (report.get("sectors") or [])][:3]
    if sec:
        lines.append("- 강한 업종: " + ", ".join(f"{s['group']}({_pct(s.get('ret1_pct'))})" for s in sec))
    return lines


def outlook(report: dict) -> list[str]:
    """내일장 예상: 지표 점수 → 우호/중립/경계 + 이유 + 확인할 지수 가격 (참고용, 예측 아님)"""
    m = report.get("market") or {}
    b = report.get("brief") or {}
    pts, why = 0.0, []
    for i in b.get("indices", []):
        t = (i["close"] >= i["ma20"]) + (i["close"] >= i["ma60"]) + (i["ma20_slope"] > 0)
        pts += (t - 1.5) / 1.5                      # -1 ~ +1
        why.append(f"{i['name']} 추세 {'강' if t == 3 else '약' if t == 0 else '중'}")
    br = m.get("breadth_pct")
    if br is not None:
        pts += (br - 50) / 25
        if br >= 60 or br <= 40:
            why.append(f"상승 종목 {br:.0f}%")
    a20 = m.get("above_sma20_pct")
    if a20 is not None:
        pts += (a20 - 50) / 50
    nd = report.get("nextday") or {}
    ga = (nd.get("grades") or {})
    if ga:
        ab = ga.get("A", 0) + ga.get("B", 0)
        pts += 0.5 if ab >= 25 else -0.5 if ab <= 5 else 0
        why.append(f"익일 후보 A·B {ab}개")
    res = (nd.get("results") or [])[:1]
    if res:
        g = (res[0].get("avg") or {}).get("gap")
        if g is not None:
            why.append(f"어제 후보 시초 갭 평균 {_pct(g, 2)}")
    view = "우호적 🟢" if pts >= 1 else "경계 🔴" if pts <= -1 else "중립 🟡"
    lines = [f"**{view}** (지표 점수 {pts:+.1f}){BR}", " · ".join(why[:4]), ""]
    for i in b.get("indices", []):
        c, m20, m60 = i["close"], i["ma20"], i["ma60"]
        if c >= m20:
            a, z = f"20일선 {m20:,.0f} 지지 확인", (f"20일 고점까지 {_pct(-i['from_high20'])}" if i["from_high20"] < -0.05 else "20일 고점 부근")
        elif c >= m60:
            a, z = f"20일선 {m20:,.0f} 회복 여부", f"60일선 {m60:,.0f} 지지"
        else:
            a, z = f"60일선 {m60:,.0f} 아래", f"반등해도 {m20:,.0f}(20일선) 저항"
        lines.append(f"- **{i['name']}** {a}{BR}")
        lines.append(f"{IND}{z}")
    lines += ["", "_※ 지표 정리이며 예측이 아닙니다. 시초가 갭 추격은 피하세요._"]
    return lines


def _tab_keys(report: dict) -> list[str]:
    st = report.get("strategies") or {}
    return [k for k in TAB_ORDER if k in st] + [k for k in st if k not in TAB_ORDER]


def picks(report: dict, per_tab: int = 3) -> list[str]:
    """내일 관심주: 탭마다 [탭 이름] → 1. 종목명 (코드) · 점수 / 다음 줄 들여써서 현재가·목표·손절, 탭 사이 한 줄 띄움"""
    lines = []
    for k in _tab_keys(report):
        v = report["strategies"][k] or {}
        cs = sorted(v.get("candidates") or [], key=lambda c: -(c.get("score") or -1))[:per_tab]
        if lines:
            lines.append("")
        lines.append(f"**[{TAB_LABEL.get(k) or v.get('short') or v.get('name') or k}]**")
        if not cs:
            lines.append(f"{IND}오늘 조건을 만족한 종목 없음")
            continue
        for n, c in enumerate(cs, 1):
            p = c.get("plan") or {}
            sc = c.get("score")
            lines.append(f"{n}. **{c['name']}** ({c['code']})" + (f" · {sc:.0f}점" if sc is not None else "") + BR)
            lines.append(f"{IND}현 {_won(p.get('price'))} · 목 {_won(p.get('target1'))} · 손 {_won(p.get('stop'))}")
    return lines


def build(report: dict, per_tab: int = 3, max_bytes: int = MAX_BYTES) -> tuple[str, str]:
    """(제목, 본문 Markdown). 길면 탭별 종목 수를 줄여 max_bytes 안으로"""
    title = f"📊 {_md(report['date'])} 장마감 리포트"
    tb, ol = today_brief(report), outlook(report)
    body = ""
    for k in range(per_tab, 0, -1):
        body = "\n".join(["### ■ 금일장 브리핑", *tb, "", "### ■ 내일장 예상", *ol, "",
                          "### ■ 내일 관심주", *picks(report, k), "",
                          "_목표·손절 = 차트 저항·지지(스윙 고저점·매물대·이평선) 기준 참고 가격_"])
        if len(body.encode("utf-8")) <= max_bytes:
            return title, body
    while len(body.encode("utf-8")) > max_bytes and "\n" in body:
        body = body.rsplit("\n", 1)[0]
    return title, body


def plain(body: str) -> str:
    """Markdown 을 못 보여주는 곳(예전 앱·텔레그램)용: 기호를 덜어낸 글"""
    import re
    t = body.replace("### ", "").replace("**", "")
    t = re.sub(r"(^|\s)_([^_\n]+)_(?=\s|$)", r"\1\2", t)
    return re.sub(r" +\n", "\n", t)
