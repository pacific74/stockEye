"""유망주 V1 (실험 탭 — 관찰용, 매매 규칙 없음)

전 거래일 장 마감 후 확정된 데이터로 다음 거래일에 '움직임'이 나올 만한 종목을 100점으로 고른다.
  A 추세 개선 25 · B 거래량·거래대금 변화 20 · C 가격 구조·종가 강도 20 · D 변동성·움직임 가능성 15
  E 시장 대비 상대 강도 10 · F 재료·위험 확인 10
- t = 선정일(장 마감). 점수는 구간표 사이를 직선으로 이어 소수점까지 (항목 배점 상한).
- 기본 제외: 우선주·스팩 · 120거래일 미만 · 20일 평균 거래대금 10억 미만 · 거래정지·관리종목 · 위험 공시/자본잠식
  (급등은 제외하지 않고 '급등 추격 위험' 태그)
- 등급: 80↑ A 우선 관찰 · 70~79 B 관심 후보 · 60~69 C 보조 후보 · 60 미만 목록 제외
- 후보 선정과 다음 날 매수 판단은 분리: 관찰 계획(지지·돌파·무효화·갭 추격 금지)을 같이 보여줌
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .reversal import ramp

VERSION = "ND-1.1"
GRADE_A, GRADE_B, GRADE_C = 80.0, 70.0, 60.0
MIN_VALUE = 10.0      # 억원 (20일 평균 거래대금)
MIN_DAYS = 120
PARTS = {"trendA": ("추세 개선", 20), "volB": ("거래량·거래대금", 20), "priceC": ("가격 구조·종가", 20),
         "movD": ("변동성·움직임", 15), "rsE": ("시장 대비 강도", 10), "newsF": ("재료·위험 (공시+뉴스)", 15)}
# 뉴스 (2026-10-12): 네이버 뉴스 최근 3일 제목 → 호재 5 · 중립/기사 없음 2.5 · 악재 0 (analysis.news_flags 가 저녁 배치에서 조정).
#   과거 뉴스는 없으므로 점수 계산·백테스트에서는 모두 중립 2.5
NEWS_NEUTRAL = 2.5

SUBS = {
    "a_g20": ("trendA", "종가와 20일선", 6), "a_s20": ("trendA", "20일선 5일 변화", 7),
    "a_s60": ("trendA", "60일선 10일 변화", 5), "a_ma": ("trendA", "20·60일선 관계", 5),
    "a_dd": ("trendA", "20일 고점 대비 하락폭", 4),
    "b_v1": ("volB", "오늘 거래량/20일", 6), "b_v5": ("volB", "5일/이전 20일 거래량", 6),
    "b_val": ("volB", "오늘 거래대금/20일", 6), "b_conf": ("volB", "거래 증가 종가 확인", 2),
    "c_pos": ("priceC", "종가 위치", 6), "c_hi": ("priceC", "20일 고점과 거리", 6),
    "c_box": ("priceC", "박스권 상단 접근", 6), "c_candle": ("priceC", "캔들 위험 없음", 2),
    "d_atr": ("movD", "ATR%", 5), "d_rv": ("movD", "5일/20일 변동성", 4), "d_sq": ("movD", "수축 후 상단 접근", 5),
    "e_1": ("rsE", "오늘 시장 대비", 5), "e_5": ("rsE", "5일 시장 대비", 5),
    "f_news": ("newsF", "공시 재료·위험", 10),
}
TYPES = ["추세 지속형", "바닥권 반등형", "거래량 증가형", "박스권 돌파 대기형", "이벤트형"]
TYPE_CHECK = {"추세 지속형": "시초가가 과도하게 뜨지 않는지, 지지 유지",
              "바닥권 반등형": "전일 저가·20일선 부근 지지 여부",
              "거래량 증가형": "거래 증가가 가격 상승으로 이어지는지",
              "박스권 돌파 대기형": "상단 돌파와 거래량 동반 여부",
              "이벤트형": "재료 진위·지속성·갭 위험"}
RULES_TEXT = [
    "A 추세: 종가가 20일선 위 2~5% · 20일선 5일 +0.5~1.5% · 60일선 상승 · 20일선 ≥ 60일선(둘 다 상승) · 20일 고점 대비 15~30% 조정",
    "B 거래: 오늘·5일 거래량/거래대금이 20일 평균의 1.3~2배 (너무 많으면 감점) · 대량 거래에 약한 종가면 0점",
    "C 가격: 종가가 하루 범위 위쪽(70%↑) · 20일 고점 2% 이내/돌파 · 좁은 박스 상단 접근/돌파 · 긴 윗꼬리·장대 음봉 없음",
    "D 변동성: ATR 2~4% · 5일/20일 변동성 0.9~1.2배 · 좁은 범위 후 상단 접근",
    "E 강도: 오늘·5일 수익률이 코스피/코스닥 지수보다 높을수록",
    "A 추세 개선은 25점 기준으로 계산해 20점으로 줄여 씀 (2026-10-12)",
    "F 재료·위험 15 = 공시 10 (없음 5점 기준 · 호재 가산 · 악재 감산) + 뉴스 5 (최근 3일 제목: 호재 5 · 중립 2.5 · 악재 0)",
    "제외: 우선주·스팩 · 120거래일 미만 · 거래대금 10억 미만 · 거래정지·관리종목 · 위험 공시·자본잠식",
    "80↑ A 우선 관찰 · 70~79 B 관심 · 60~69 C 보조 · 관찰용 (다음 날 갭·거래량·지지 확인 후 판단)",
]

K = {
    "a_g20": [(-0.5, 0), (1, 4), (2.5, 6), (4.5, 6), (6.5, 3)],
    "a_s20": [(-1.25, 0), (-0.5, 2), (0.25, 4), (0.75, 7), (1.25, 7), (2.5, 5)],
    "a_s60": [(-2.5, 0), (-1.25, 1), (-0.25, 3), (0.5, 5), (1, 5), (2, 4)],
    "a_dd": [(-32, 2), (-22.5, 4), (-10, 3), (-2.5, 1)],
    "b_v": [(0.6, 0), (0.85, 2), (1.25, 4), (1.6, 6), (1.9, 6), (2.5, 4)],
    "b_v5": [(0.7, 0), (0.9, 2), (1.15, 4), (1.4, 6), (1.7, 6), (2.2, 4)],
    "b_conf": [(0.5, 1), (0.8, 2)],
    "c_pos": [(0.25, 0), (0.4, 2), (0.6, 4), (0.75, 6)],
    "c_hi": [(-12, 0), (-7.5, 2), (-3.5, 4), (-2, 6)],
    "box_pos": [(0.5, 0), (0.95, 1)],           # 박스 안 위치 → 0~1
    "d_atr": [(0.5, 1), (1.5, 3), (2.3, 5), (3.7, 5), (5, 3), (7, 1)],
    "d_rv": [(0.6, 1), (0.8, 3), (1.05, 4), (1.35, 3), (1.7, 1)],
    "e_1": [(-2.5, 0), (-1.25, 1), (0, 3), (1.25, 4), (2.5, 5)],
    "e_5": [(-0.5, 0), (0.5, 1), (2, 3), (3.5, 5)],
}


def _wilder(s, n=14):
    return s.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def raw_features(O, H, L, C, V, VAL, idx_ret: dict, market_of: dict, dates=None) -> dict:
    """넓은 표 → 원자료. idx_ret = {'KOSPI': (ret1 Series, ret5 Series), ...} (%, 날짜 인덱스)"""
    f = {}
    ma5, ma20, ma60 = (C.rolling(n, min_periods=n).mean() for n in (5, 20, 60))
    f["NDAYS"] = C.notna().cumsum()
    f["G20"] = 100 * (C / ma20 - 1)
    f["S20"] = 100 * (ma20 / ma20.shift(5) - 1)
    f["S60"] = 100 * (ma60 / ma60.shift(10) - 1)
    f["MA_UP"] = ma20 >= ma60
    hi20 = H.rolling(20, min_periods=20).max()
    f["DD20"] = 100 * (C / hi20 - 1)
    v20p = V.shift(1).rolling(20, min_periods=20).mean()
    f["V1"] = V / v20p.where(v20p > 0)
    v20pp = V.shift(5).rolling(20, min_periods=20).mean()
    f["V5"] = V.rolling(5, min_periods=5).mean() / v20pp.where(v20pp > 0)
    val = VAL if VAL is not None else C * V
    a20p = val.shift(1).rolling(20, min_periods=20).mean()
    f["VAL1"] = val / a20p.where(a20p > 0)
    f["VAL20"] = val.rolling(20, min_periods=20).mean() / 1e8
    rng = H - L
    f["P"] = ((C - L) / rng).where(rng > 0)
    hp = H.shift(1).rolling(20, min_periods=20).max()            # 어제까지 20일 고점
    lp = L.shift(1).rolling(20, min_periods=20).min()
    f["HI20"] = 100 * (C / hp - 1)
    w20 = 100 * (hp / lp - 1)                                     # 최근 박스 폭
    w_prev = 100 * (H.shift(21).rolling(20, min_periods=20).max() / L.shift(21).rolling(20, min_periods=20).min() - 1)
    f["BOXW"], f["BOXW_PREV"] = w20, w_prev
    f["SQUEEZE"] = (w20 <= 15) | (w20 < 0.7 * w_prev)
    f["BOXPOS"] = ((C - lp) / (hp - lp)).where(hp > lp)
    prev_c = C.shift(1)
    tr = np.maximum(rng, np.maximum((H - prev_c).abs(), (L - prev_c).abs()))
    atr = _wilder(tr)
    f["ATR"] = 100 * atr / C
    upper = H - np.maximum(O, C)
    body_dn = (O - C) / C
    f["CANDLE_RISK"] = (((upper / rng.where(rng > 0)) >= 0.5) & (rng >= atr)) | (body_dn >= np.maximum(0.03, atr / C))
    r = C.pct_change(fill_method=None)
    f["RV"] = r.rolling(5, min_periods=5).std() / r.rolling(20, min_periods=20).std()
    f["R1"], f["R5"] = 100 * r, 100 * (C / C.shift(5) - 1)
    mk = pd.Series([market_of.get(c, "KOSPI") for c in C.columns], index=C.columns)
    for k, j in (("EX1", 0), ("EX5", 1)):
        base = pd.DataFrame({c: idx_ret.get(m, (pd.Series(dtype=float),) * 2)[j].reindex(C.index) for c, m in mk.items()})
        f[k] = (f["R1"] if j == 0 else f["R5"]) - base
    f["MA5_20"] = ma5 > ma20
    if dates is not None:
        f = {k: v.reindex(dates) for k, v in f.items()}
    return f


def index_returns(index: pd.DataFrame) -> dict:
    out = {}
    for m, g in index.groupby("code"):
        s = g.set_index("date")["close"].sort_index().astype(float)
        out[m] = (100 * s.pct_change(), 100 * (s / s.shift(5) - 1))
    return out


def score_frame(f: dict, news=None, has_news: bool = True) -> dict:
    """원자료 → 세부 점수. news = 기존 공시 점수(0~15, 기본 7) 단면 Series"""
    like = f["G20"]
    wrap = (lambda a: pd.DataFrame(a, index=like.index, columns=like.columns)) if isinstance(like, pd.DataFrame) \
        else (lambda a: pd.Series(a, index=like.index))
    a = lambda k: np.asarray(f[k], dtype=float)  # noqa: E731
    b = lambda k: np.asarray(f[k], dtype=bool)   # noqa: E731
    s = {}
    s["a_g20"] = wrap(ramp(a("G20"), K["a_g20"]))
    s["a_s20"] = wrap(ramp(a("S20"), K["a_s20"]))
    s["a_s60"] = wrap(ramp(a("S60"), K["a_s60"]))
    both_up = (a("S20") > 0) & (a("S60") > 0)
    s["a_ma"] = wrap(np.where(b("MA_UP"), np.where(both_up, 5.0, 3.0), 0.0))
    s["a_dd"] = wrap(ramp(a("DD20"), K["a_dd"]))
    s["b_v1"] = wrap(ramp(a("V1"), K["b_v"]))
    s["b_v5"] = wrap(ramp(a("V5"), K["b_v5"]))
    s["b_val"] = wrap(ramp(a("VAL1"), K["b_v"]))
    surge = a("V1") >= 1.5
    p = a("P")
    conf = np.where(np.isnan(p), 1.0, np.where(surge & (p < 0.5), 0.0, np.where(p < 0.5, 1.0, ramp(p, K["b_conf"]))))
    s["b_conf"] = wrap(conf)
    s["c_pos"] = wrap(np.where(np.isnan(p), 3.0, ramp(p, K["c_pos"])))          # 고가=저가 → 중립 3
    s["c_hi"] = wrap(ramp(a("HI20"), K["c_hi"]))
    sq, bp, hi = b("SQUEEZE"), a("BOXPOS"), a("HI20")
    box = np.where(~sq, 0.0, np.where(hi > 0, 6.0, 2 + 2 * np.nan_to_num(ramp(bp, K["box_pos"]))))
    s["c_box"] = wrap(np.where(np.isnan(bp) & np.isnan(hi), np.nan, box))
    s["c_candle"] = wrap(np.where(b("CANDLE_RISK"), 0.0, 2.0))
    s["d_atr"] = wrap(ramp(a("ATR"), K["d_atr"]))
    s["d_rv"] = wrap(ramp(a("RV"), K["d_rv"]))
    s["d_sq"] = wrap(np.where(~sq, 0.0, np.where(hi > -2, 5.0, 2 + 3 * np.nan_to_num(ramp(bp, K["box_pos"])))))
    s["e_1"] = wrap(ramp(a("EX1"), K["e_1"]))
    s["e_5"] = wrap(ramp(a("EX5"), K["e_5"]))
    if news is None or not has_news:
        s["f_news"] = wrap(np.full(np.shape(a("G20")), 5.0))                     # 정보 미확인 → 중립
    else:
        n = np.asarray(news.reindex(like.index) if isinstance(news, pd.Series) else news, dtype=float)
        n = np.where(np.isnan(n), 7.0, n)
        s["f_news"] = wrap(np.where(n >= 7, 5 + (n - 7) / 8 * 5, 5 * n / 7).clip(0, 10))
    return s


def totals(s: dict) -> dict:
    out = {}
    for p, (_, mx) in PARTS.items():
        tot = None
        for k, (pp, _, _) in SUBS.items():
            if pp == p:
                tot = s[k].fillna(0) if tot is None else tot + s[k].fillna(0)
        if p == "trendA":
            out[p] = tot.clip(upper=25) * (20 / 25)                # 추세 개선 25 → 20 (세부 점수는 그대로, 비율로)
        elif p == "newsF":
            out[p] = tot.clip(upper=10) + NEWS_NEUTRAL             # 공시 10 + 뉴스 5 (중립 2.5)
        else:
            out[p] = tot.clip(upper=mx)
    out["total"] = sum(out[p] for p in PARTS)
    return out


def grade(total: float) -> tuple[str, str]:
    if total >= GRADE_A:
        return "A", "우선 관찰"
    if total >= GRADE_B:
        return "B", "관심 후보"
    if total >= GRADE_C:
        return "C", "보조 후보"
    return "-", "낮은 우선순위"


def types_of(r) -> list[str]:
    """후보 유형 (여러 개 가능, 앞이 대표)"""
    g = lambda k: r.get("rv_" + k)  # noqa: E731
    ok = lambda v: v is not None and v == v  # noqa: E731
    t = []
    if r.get("f_news", 5) >= 7:
        t.append("이벤트형")
    if bool(g("SQUEEZE")) and ok(g("BOXPOS")) and g("BOXPOS") >= 0.8:
        t.append("박스권 돌파 대기형")
    if bool(g("MA_UP")) and ok(g("S20")) and g("S20") > 0 and ok(g("S60")) and g("S60") > 0 and ok(g("EX5")) and g("EX5") > 0:
        t.append("추세 지속형")
    if ok(g("DD20")) and g("DD20") <= -15 and ok(g("G20")) and g("G20") > -3:
        t.append("바닥권 반등형")
    if ok(g("V1")) and (g("V1") >= 1.5 or (ok(g("V5")) and g("V5") >= 1.3)):
        t.append("거래량 증가형")
    order = {k: i for i, k in enumerate(["이벤트형", "박스권 돌파 대기형", "추세 지속형", "바닥권 반등형", "거래량 증가형"])}
    return sorted(t, key=order.get) or ["거래량 증가형" if ok(g("V1")) and g("V1") >= 1 else "추세 지속형"]


def tags_of(r) -> list[str]:
    g = lambda k: r.get("rv_" + k)  # noqa: E731
    ok = lambda v: v is not None and v == v  # noqa: E731
    t = []
    if ok(g("R1")) and g("R1") >= 20:
        t.append("급등 추격 위험")
    if ok(g("ATR")) and g("ATR") > 6:
        t.append("변동성 큼")
    if ok(g("V1")) and g("V1") >= 1.5 and ok(g("P")) and g("P") < 0.5:
        t.append("대량 거래 + 약한 종가")
    if bool(g("CANDLE_RISK")):
        t.append("긴 윗꼬리·장대 음봉")
    if not r.get("has_news", True):
        t.append("공시 정보 미확인")
    return t


def rank(sc: pd.DataFrame, ok: pd.Series, value: pd.Series, min_score: float = GRADE_C) -> pd.DataFrame:
    o = sc[ok.astype(bool).reindex(sc.index, fill_value=False) & (sc["total"] >= min_score)].copy()
    o["_v"] = value.reindex(o.index).fillna(0)
    o["_c"] = o.index
    o = o.sort_values(["total", "trendA", "volB", "_v", "_c"], ascending=[False, False, False, False, True])
    return o.drop(columns=["_v", "_c"])


def common_stock(code: str, name: str) -> bool:
    """보통주만 (우선주: 코드 끝자리 0 아님 / 스팩·ETF·ETN·리츠 제외)"""
    if not code or code[-1] != "0":
        return False
    n = str(name or "")
    return not any(w in n for w in ("스팩", "ETN", "ETF", "리츠"))
