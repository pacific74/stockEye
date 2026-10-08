"""V2 공시 점수 (15점) + 매수 차단 — DART 공시 '제목' 규칙 기반.

뉴스(언론 기사)는 아직 넣지 않는다 (과거 데이터가 없어 백테스트 검증이 안 됨).
공시의 '개수'가 아니라 '종류'로 점수를 준다. 같은 종류는 기간 안에서 한 번만 센다.

점수 = 기본 7점(중립) + 최근 60일 좋은 공시 − 최근 60~180일 나쁜 공시, 0~15 로 자름.
차단 = 점수와 관계없이 매수 후보에서 제외 (관리종목·상장폐지·감사의견·횡령배임·대규모 증자 등).

[미래참조] 공시는 접수일 23:59 에 공개된 것으로 본다 (DART 목록에 시각이 없음) → 그다음 날부터 사용.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

# (이름, 정규식, 점수, 반영 기간(일), 차단 사유 또는 None)
#  - 순서대로 처음 맞는 규칙 하나만 적용
RULES: list[tuple[str, str, float, int, str | None]] = [
    # ---- 매수 차단 (위험) ----
    ("관리해제", r"관리종목.*해제", 0, 0, None),                              # 해제는 따로 처리 (지정보다 먼저 검사)
    ("상장폐지", r"상장폐지|상장적격성|정리매매", -15, 365, "상장폐지 관련"),
    ("관리종목", r"관리종목지정|관리종목\s*지정", -15, 365, "관리종목"),
    ("감사의견", r"감사의견(거절|부적정|한정)|의견거절|감사범위제한", -15, 365, "감사의견 문제"),
    ("횡령배임", r"횡령|배임", -10, 365, "횡령·배임"),
    ("회생부도", r"회생절차|파산|부도|해산사유", -15, 365, "회생·부도"),
    ("투자위험", r"투자위험종목|투자경고종목", -5, 20, "투자경고·위험 지정(과열)"),
    ("매매정지", r"매매거래정지|거래정지", -5, 10, "거래정지"),
    ("감자", r"감자결정", -8, 180, "감자"),
    ("대규모유증", r"유상증자결정.*(주주배정|일반공모)|(주주배정|일반공모).*유상증자", -6, 120, "대규모 유상증자"),
    # ---- 감점 ----
    ("유상증자", r"유상증자결정", -4, 120, None),                          # 제3자배정 등
    ("전환사채", r"전환사채권발행결정|전환사채\(.*\)발행결정", -4, 120, None),
    ("신주인수권", r"신주인수권부사채권발행결정", -4, 120, None),
    ("교환사채", r"교환사채권발행결정", -2, 90, None),
    ("불성실공시", r"불성실공시법인", -3, 180, None),
    ("소송", r"소송등의제기|소송등의\s*제기|가압류|가처분", -2, 90, None),
    ("투자주의", r"투자주의환기|투자주의종목", -2, 30, None),
    ("최대주주변경", r"최대주주변경", -1, 60, None),
    ("실적감소", r"영업실적.*감소|손실.*확대|적자전환", -3, 60, None),
    # ---- 가점 ----
    ("수주", r"단일판매|공급계약체결|판매ㆍ공급계약|수주", 4, 60, None),
    ("실적개선", r"흑자전환|영업실적.*증가|잠정실적.*증가", 4, 60, None),
    ("자사주", r"자기주식취득결정|자기주식취득신탁|주식소각결정|자기주식\s*소각", 2, 60, None),
    ("배당확대", r"현금ㆍ현물배당결정|현금·현물배당결정|분기배당|중간배당", 1, 60, None),
    ("무상증자", r"무상증자결정", 2, 60, None),
    ("신규투자", r"신규시설투자|유형자산취득결정", 2, 60, None),
    ("특허기술", r"특허권취득|기술이전|기술도입", 1, 60, None),
]
_COMPILED = [(n, re.compile(rx), sc, days, blk) for n, rx, sc, days, blk in RULES]
BASE = 7.0
MAX = 15.0


def classify(title: str) -> tuple[str, float, int, str | None] | None:
    t = str(title).replace(" ", "")
    if t.startswith("[기재정정]") or t.startswith("[첨부정정]"):
        t = t.split("]", 1)[1]
    for name, rx, sc, days, blk in _COMPILED:
        if rx.search(t):
            return name, sc, days, blk
    return None


@dataclass
class DisclosureIndex:
    """종목별 분류된 공시 (날짜순). 날짜 d 시점(18:00 판단) 점수·차단을 빠르게 계산."""
    events: dict  # code -> DataFrame(date, name, score, days, block)

    @classmethod
    def build(cls, disc: pd.DataFrame) -> "DisclosureIndex":
        if disc is None or disc.empty:
            return cls({})
        rows = []
        for code, t, title in zip(disc["code"], disc["published_at"], disc["title"]):
            c = classify(title)
            if c:
                rows.append((code, pd.Timestamp(t), *c, title))
        if not rows:
            return cls({})
        ev = pd.DataFrame(rows, columns=["code", "date", "name", "score", "days", "block", "title"])
        ev = ev.sort_values(["code", "date"])
        return cls({c: g.reset_index(drop=True) for c, g in ev.groupby("code", sort=False)})

    def at(self, code: str, as_of: pd.Timestamp) -> dict:
        """{score(0~15), block(사유 목록), pos(제목), neg(제목)}  — as_of 이전에 공개된 것만"""
        g = self.events.get(code)
        out = {"score": BASE, "block": [], "pos": [], "neg": []}
        if g is None:
            return out
        g = g[g["date"] < as_of]
        if g.empty:
            return out
        age = (as_of - g["date"]).dt.days
        live = g[age <= g["days"]]
        # 관리종목: 지정 뒤 해제가 있으면 차단 풀림
        admin = g[g["name"].isin(["관리종목", "관리해제"])]
        admin_on = not admin.empty and admin.iloc[-1]["name"] == "관리종목"
        seen = set()
        score = BASE
        for _, e in live.iloc[::-1].iterrows():        # 최근 것부터, 같은 종류는 한 번만
            if e["name"] in seen or e["name"] == "관리해제":
                continue
            seen.add(e["name"])
            if e["name"] == "관리종목" and not admin_on:
                continue
            score += e["score"]
            if e["block"]:
                out["block"].append(e["block"])
            (out["pos"] if e["score"] > 0 else out["neg"]).append(e["title"])
        if admin_on and "관리종목" not in out["block"]:
            out["block"].append("관리종목")
        out["score"] = float(np.clip(score, 0, MAX))
        return out
