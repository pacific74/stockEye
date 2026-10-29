

def test_replay_day_min_score_accepts_lower_score(monkeypatch):
    """min_score 를 주면 '진입 조건 충족'(80↑)이 아니어도 신호·점수 기준만 맞으면 진입 — 기준 비교용"""
    import pandas as pd
    from stockeye.analysis import daytrade_eval as de

    seq = iter([
        {"status": "관찰", "signal": True, "excluded": [], "score": 77.0, "warnings": [], "time": "09:20", "type": "돌파",
         "entry": 100, "stop": 98, "t1": 103, "t2": 105, "parts": {}},
    ] * 100)
    monkeypatch.setattr(de.dt, "evaluate", lambda b, ctx: next(seq))
    t = pd.date_range("2026-10-13 09:00", periods=30, freq="min")
    bars = pd.DataFrame({"time": t, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0})
    assert de.replay_day(bars, 99.0) is None                              # 기본(80↑ 상태)은 진입 없음
    assert de.replay_day(bars, 99.0, min_score=75)["score"] == 77.0
    assert de.replay_day(bars, 99.0, min_score=78) is None                # 기준 미달


def test_replay_day_extra_and_only_type(monkeypatch):
    """extra 는 엔진 ctx 로 전달 · only_type 은 그 유형 신호만 진입"""
    import pandas as pd
    from stockeye.analysis import daytrade_eval as de

    seen = []

    def fake(b, ctx):
        seen.append(ctx)
        return {"status": "진입 조건 충족", "signal": True, "excluded": [], "score": 85.0, "warnings": [], "time": "09:20",
                "type": "눌림목", "entry": 100, "stop": 98, "t1": 103, "t2": 105, "parts": {}}
    monkeypatch.setattr(de.dt, "evaluate", fake)
    t = pd.date_range("2026-10-13 09:00", periods=30, freq="min")
    bars = pd.DataFrame({"time": t, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0})
    assert de.replay_day(bars, 99.0, extra={"hi_n": 123.0, "rebound": {"why": "x"}})["type"] == "눌림목"
    assert seen[0]["hi_n"] == 123.0 and seen[0]["rebound"] == {"why": "x"}
    assert de.replay_day(bars, 99.0, only_type="돌파") is None
    assert de.replay_day(bars, 99.0, only_type="눌림목") is not None


def test_rank_score_none_when_excluded_or_short(monkeypatch):
    import pandas as pd
    from stockeye.analysis import daytrade_eval as de

    monkeypatch.setattr(de.dt, "evaluate", lambda b, ctx: {"excluded": [], "score": 83.0})
    t = pd.date_range("2026-10-13 09:00", periods=30, freq="min")
    bars = pd.DataFrame({"time": t, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0})
    assert de.rank_score(bars, 99.0, "09:10") == 83.0
    assert de.rank_score(bars.head(6), 99.0, "09:10") is None            # 09:10 까지 5봉 미만이 아니면 계산
    monkeypatch.setattr(de.dt, "evaluate", lambda b, ctx: {"excluded": ["x"], "score": 90.0})
    assert de.rank_score(bars, 99.0, "09:10") is None


def test_scan_then_first_entry_matches_replay(monkeypatch):
    import pandas as pd
    from stockeye.analysis import daytrade_eval as de

    def fake(b, ctx):
        n = len(b)
        return {"status": "진입 조건 충족" if n >= 12 else "관찰", "signal": n >= 12, "excluded": [], "score": 70.0 + n,
                "warnings": [], "time": "x", "type": "돌파" if n < 15 else "눌림목", "entry": 100, "stop": 98, "t1": 103, "t2": 105, "parts": {}}
    monkeypatch.setattr(de.dt, "evaluate", fake)
    t = pd.date_range("2026-10-13 09:00", periods=40, freq="min")
    bars = pd.DataFrame({"time": t, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0})
    sc = de.scan_day(bars, 99.0)
    assert de.first_entry(sc) == de.replay_day(bars, 99.0)
    assert de.first_entry(sc, only_type="눌림목")["type"] == "눌림목"
    assert de.first_entry(sc, start="09:10") is not None
    assert de.rank_from_scan(sc, "09:10") == 70.0 + 11                    # 09:10 봉까지 11개
