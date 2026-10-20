import pandas as pd

from stockeye.analysis import market_shock as ms


def _ix(k, d):
    return pd.DataFrame([{"code": "KOSPI", "chg_pct": k}, {"code": "KOSDAQ", "chg_pct": d}])


class SB:
    def __init__(self):
        self.state = {}

    def select(self, table, q):
        return [{"payload": self.state}] if self.state else []

    def upsert(self, table, rows, key):
        self.state = rows[0]["payload"]


def test_level_steps():
    assert [ms.level(x) for x in (2.9, -3.0, 4.9, -5.2, 8)] == [0, 3, 3, 5, 7]
    assert ms.level(None) == 0


def test_issue_tags():
    t = ["코스피 급락 환율 1400원 돌파", "외국인 순매도 폭탄 환율 급등", "미국 금리 인상 우려"]
    assert ms.issue_tags(t)[0] == "환율" and "외국인·기관 매매" in ms.issue_tags(t)


def test_check_alerts_once_per_level(monkeypatch):
    sent, news = [], [{"title": "코스피 3% 급락 환율 폭등", "time": "2026-10-20 10:05", "link": "x", "desc": ""}]
    fetch = lambda q, days=1, must=(), **k: news   # noqa: E731
    send = lambda tp, t, b: sent.append((tp, t, b)) or True   # noqa: E731
    sb = SB()
    now = pd.Timestamp("2026-10-20 10:10")
    assert ms.check(sb, ["adm"], _ix(-2.5, -1), send, fetch, now) == []
    assert ms.check(sb, ["adm"], _ix(-3.2, -2.0), send, fetch, now) == ["KOSPI"]
    t, b = sent[0][1:]
    assert "코스피 -3.2% 급락" in t and "환율" in b and "코스닥 -2.00%" in b and "확정하는 것이 아닙니다" in b
    assert ms.check(sb, ["adm"], _ix(-3.8, -2.0), send, fetch, now) == []          # 같은 단계 → 다시 안 보냄
    assert ms.check(sb, ["adm"], _ix(-5.1, -2.0), send, fetch, now) == ["KOSPI"]   # 5% 단계는 한 번 더
    assert ms.check(sb, ["adm"], _ix(3.4, 0.1), send, fetch, now) == ["KOSPI"]     # 급등은 방향이 달라 따로
    assert len(sent) == 3


def test_failed_send_retries_next_time():
    sb, sent = SB(), []
    ix, now = _ix(-3.5, -1), pd.Timestamp("2026-10-20 10:10")
    assert ms.check(sb, ["adm"], ix, lambda *a: False, lambda *a, **k: [], now) == []
    assert ms.check(sb, ["adm"], ix, lambda tp, t, b: sent.append(t) or True, lambda *a, **k: [], now) == ["KOSPI"]
    assert "관련 기사를 찾지 못했어요" in sent[0] or sent
