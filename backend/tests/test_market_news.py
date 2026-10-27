import pandas as pd

from stockeye.analysis import market_news as mn


class FakeSb:
    def __init__(self): self.rows = {}
    def select(self, t, q): return [{"payload": self.rows["market_news"]}] if "market_news" in self.rows else []


def test_run_publishes_five_and_skips_recent(monkeypatch):
    def fake(q, days=1, must=(), **kw):
        names = ["엔비디아 실적 기대감에 반도체 급등 이유", "외국인 순매수 확대 배경은", "미국 금리 인하 전망 영향", "원달러 환율 하락 여파",
                 "삼성전자 HBM 수주 호재", "중동 휴전 소식에 유가 급락", "정부 세제 개편안 발표 파장", "2차전지 업종 반등 이유"]
        return [{"title": nm, "link": f"http://x/{i}", "time": f"2026-10-27 09:{10+i}"} for i, nm in enumerate(names)]
    sb, saved = FakeSb(), {}
    from stockeye.cloud import publish as pub
    monkeypatch.setattr(pub, "publish_status", lambda s, k, p: (saved.__setitem__(k, p), s.rows.__setitem__(k, p)))
    idx = pd.DataFrame([{"code": "KOSPI", "chg_pct": 3.6}, {"code": "KOSDAQ", "chg_pct": 3.0}])
    now = pd.Timestamp("2026-10-27 10:10")
    p = mn.run(sb, idx, fake, now)
    assert p and len(p["items"]) == 5 and p["index"] == "KOSPI" and p["items"][0]["link"]
    assert mn.run(sb, idx, fake, pd.Timestamp("2026-10-27 10:20")) is None      # 25분 안엔 건너뜀
    assert mn.run(sb, idx, fake, pd.Timestamp("2026-10-27 10:40")) is not None


def test_no_news_no_publish(monkeypatch):
    assert mn.run(FakeSb(), pd.DataFrame([{"code": "KOSPI", "chg_pct": 0.2}]), lambda *a, **k: [], pd.Timestamp("2026-10-27 10:10")) is None
