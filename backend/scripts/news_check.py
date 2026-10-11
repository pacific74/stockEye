"""네이버 뉴스(API HUB) 키·호출 확인: python -m scripts.news_check 삼성전자"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from stockeye.data import naver_news as nn  # noqa: E402
from stockeye.analysis.news_flags import judge  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
name = (sys.argv[1] if len(sys.argv) > 1 else "삼성전자").strip()
if not nn.enabled():
    sys.exit("NAVER_HUB_ID / NAVER_HUB_SECRET 가 없습니다 (GitHub Secrets 확인)")
items = nn.fetch(name)
j = judge(items)
print(f"[{name}] 최근 3일 뉴스 {len(items)}건 (중복 제거 후) · 판정 {j['level'] or '중립'} {j['word'] or ''}")
for it in items[:10]:
    print(f"  {it['time']}  {it['title']}")
if not items:
    print("  (없음 — 키가 맞는데 0건이면 최근 3일 기사가 없거나 종목명이 제목에 없는 경우)")
