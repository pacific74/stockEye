"""공시/뉴스 제목 키워드 점수 (1단계: 규칙 기반. 2단계에서 AI 분석으로 교체 예정)."""
from __future__ import annotations

POSITIVE = ["공급계약", "판매ㆍ공급", "수주", "자기주식취득", "자사주", "무상증자", "특허",
            "기술이전", "흑자전환", "영업실적 증가", "현금ㆍ현물배당", "주식소각"]
NEGATIVE = ["유상증자", "전환사채", "신주인수권부사채", "교환사채", "횡령", "배임", "소송",
            "감자", "불성실공시", "관리종목", "거래정지", "감사의견", "상장적격성", "회생", "부도",
            "최대주주변경", "투자주의", "투자경고", "투자위험"]


def classify(title: str) -> int:
    t = title.replace(" ", "")
    if any(k.replace(" ", "") in t for k in NEGATIVE):
        return -1
    if any(k.replace(" ", "") in t for k in POSITIVE):
        return 1
    return 0


def news_fraction(titles: list[str]) -> tuple[float, list[str], list[str]]:
    """0~1 점수, 긍정 제목들, 부정 제목들. 공시 없음 = 0.5 (중립)."""
    pos = [t for t in titles if classify(t) > 0]
    neg = [t for t in titles if classify(t) < 0]
    frac = 0.5 + 0.25 * len(pos) - 0.5 * len(neg)
    return max(0.0, min(1.0, frac)), pos, neg
