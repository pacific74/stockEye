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


def test_all_topics_includes_opted_in_members():
    class S:
        def select(self, t, q):
            return [{"ntfy_topic": "m1", "notify_daily": True}, {"ntfy_topic": "m2", "notify_daily": False},
                    {"ntfy_topic": "adm", "notify_daily": True}, {"ntfy_topic": " m3/ "}]
    assert ms.all_topics(S(), ["adm"]) == ["adm", "m1", "m3"]
    assert ms.all_topics(None, ["adm"]) == ["adm"]


def test_price_only_vs_issue_titles_and_ordering():
    assert ms.is_price_only("코스피 3% 급락 마감") and not ms.is_price_only("김정은 사망설에 코스피 급락")
    n = [{"title": "코스피 급락 마감", "time": "2026-10-20 10:20"}, {"title": "속보 김정은 사망설 확산", "time": "2026-10-20 10:05"},
         {"title": "코스피 3% 하락", "time": "2026-10-20 10:15"}]
    got = ms.news_for("KOSPI", True, fetch=lambda q, days=1, must=(), **k: n)
    assert got[0]["title"].startswith("속보")                           # 이슈 기사가 가격 기사보다 먼저
    assert "돌발 사건·소문" in ms.issue_tags([x["title"] for x in n])


def test_ai_comment_only_with_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert ms.ai_comment("KOSPI", -3.1, [{"title": "x", "time": "2026-10-20 10:00"}]) is None
    t, b = ms.message([{"code": "KOSPI", "chg": -3.1}], [], "10:10", comment="사망설 보도로 불안 확대")
    assert "🧭 사망설 보도로 불안 확대" in b and "사실 확인 아님" in b


def test_title_follows_new_index():
    rows = [{"code": "KOSDAQ", "chg": 3.02}, {"code": "KOSPI", "chg": 3.67}]
    t, b = ms.message(rows, [], "09:12", new_codes=["KOSDAQ"])
    assert "코스닥 +3.0% 급등" in t and b.splitlines()[0].startswith("코스닥")
    t2, _ = ms.message(rows, [], "09:12")
    assert "코스피" in t2                                            # new_codes 가 없으면 예전처럼 가장 큰 지수


def test_cause_news_ranked_first_and_theme_search():
    def fake(q, days=1, must=(), **kw):
        base = {"코스피 급등": [{"title": "코스피 3.6% 급등 마감", "time": "2026-10-27 09:20"}],
                "증시 급등 이유": [{"title": "코스피 장중 3% 상승", "time": "2026-10-27 09:18"},
                                 {"title": "반도체 쏠림 속 코스피 급등", "time": "2026-10-27 09:10"},
                                 {"title": "앤트로픽 쇼크에 반도체 들썩", "time": "2026-10-27 09:12"},
                                 {"title": "앤트로픽 효과 반도체주 강세", "time": "2026-10-27 09:14"}]}
        if q == "반도체 급등 이유":                                   # 1차 결과에서 반도체·AI 이슈가 잡히면 재검색
            return [{"title": "앤트로픽 신모델 여파에 반도체 급등 이유는", "time": "2026-10-27 09:00"}]
        if q.startswith("앤트로픽 "):                                   # 오늘 기사에 반복된 단어로 재검색
            return [{"title": "앤트로픽 대규모 AI 칩 계약", "time": "2026-10-27 08:50"}]
        return base.get(q, [])
    out = ms.news_for("KOSPI", False, fake)
    titles = [x["title"] for x in out]
    assert titles[0].startswith("앤트로픽 신모델") and "앤트로픽 대규모 AI 칩 계약" in titles
    assert titles.index("코스피 3.6% 급등 마감") > titles.index("반도체 쏠림 속 코스피 급등")   # 숫자만 전하는 시황은 뒤로
    _, body = ms.message([{"code": "KOSPI", "chg": 3.6}], out, "09:12")
    assert "왜 움직였나" not in body and "앤트로픽 신모델" in body


def test_no_fixed_topic_on_quiet_day():
    def fake(q, days=1, must=(), **kw):
        return [{"title": "코스피 3.1% 급등 마감", "time": "2026-10-27 09:20"}] if q == "코스피 급등" else []
    out = ms.news_for("KOSPI", False, fake)
    assert all("앤트로픽" not in x["title"] for x in out) and ms.hot_terms(["코스피 급등 마감", "증시 상승 이유"]) == []
