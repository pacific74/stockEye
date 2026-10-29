

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
