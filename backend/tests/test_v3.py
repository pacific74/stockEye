"""V3 기준 전략 (🔒 고정 규칙) — 규칙이 몰래 바뀌지 않게 지키는 시험"""
import numpy as np
import pandas as pd

from stockeye.engine import v3


def test_rules_locked():
    assert v3.VERSION == "V3B-2.1" and v3.LOCKED_AT == "2026-10-11"
    assert v3.RULES == {"top_n": 10, "every": 5, "hold": 20, "max_positions": 20, "weight": 0.05, "market_weight": 1.0,
                        "on_reselect": "extend", "add_buy": False, "buy_cost": 0.0015, "sell_cost": 0.0025}
    assert {k: m for k, (_, m) in v3.PARTS.items()} == {"vola15": 15, "fin25": 25, "pos20": 20, "trend5": 5, "vol5": 5,
                                                         "value5": 5, "flow10": 10, "news15": 15}


def _x(n=6):
    idx = [f"{i:06d}" for i in range(n)]
    base = dict(close=10000.0, sma20=10000.0, sma60=9800.0, sma60_slope=0.01, dist_sma20=0.0, low20=9600.0,
                high20_prev=10800.0, ret5=0.0, ret20=0.02, up_day=True, touch_sma20_3d=1.0, atr_pct=0.02, rsi14=50.0,
                vol_ratio=1.0, per=10.0, pbr=1.0, eps_yoy=0.1, value_ma20=5e9)
    return pd.DataFrame([base] * n, index=idx)


def test_score_and_filters():
    x = _x()
    x.loc["000001", "ret5"] = 0.25            # 과열 → 자격 없음
    x.loc["000002", "atr_pct"] = 0.09         # 변동성 큼 → 변동성 0점
    x.loc["000003", ["close", "sma60_slope"]] = [9000.0, -0.05]   # 60일선 아래 + 급락 → 추세 필터 탈락
    blocked = pd.Series(False, index=x.index)
    blocked["000004"] = True                  # V2 매수 차단
    fin = pd.DataFrame({"op_pos": True, "roe": 0.2, "op_margin": 0.1, "rev_yoy": 0.1, "op_yoy": 0.2, "ni_yoy": 0.2,
                        "op_improve": True, "debt_ratio": 0.5, "current_ratio": 2.0, "impaired": False}, index=x.index)
    o = v3.score(x, blocked, fin, {})
    assert o.loc["000000", "vola15"] == 15 and o.loc["000002", "vola15"] == 0
    assert o.loc["000000", "fin25"] == 24                      # 수익성 8 + 성장 7 + 건전 6 + 밸류 3 (업종 중앙값과 같아 +1 없음)
    assert not o.loc["000001", "eligible"] and not o.loc["000003", "eligible"] and not o.loc["000004", "eligible"]
    assert o.loc["000000", "eligible"] and o.loc["000005", "eligible"]
    assert o.loc["000000", "v3b"] == o.loc["000000", list(v3.PARTS)].sum()
    assert v3.MAX_SCORE == 100
    o2 = v3.score(x, blocked, pd.DataFrame(), {})               # 재무 없음 = 10점, ev 없음 = 중간값
    assert (o2["fin25"] == 10).all() and (o2["news15"] == 7.5).all() and (o2["flow10"] == 5).all()


def test_trend_and_ev_parts():
    x = _x(2)
    x["vol5_ratio"] = [1.0, 2.5]
    x.loc["000001", ["close", "sma60_slope", "sma20"]] = [9500.0, -0.01, 9700.0]   # 60일선 아래·하락·20<60
    ev = pd.DataFrame({"value": [5, 1], "flow": [15, 3], "news": [12, 4]}, index=x.index)
    o = v3.score(x, pd.Series(False, index=x.index), pd.DataFrame(), {}, ev)
    assert list(o["trend5"]) == [5, 0] and list(o["vol5"]) == [5, 0]
    assert list(o["value5"]) == [5, 1] and list(o["flow10"]) == [10, 2] and list(o["news15"]) == [12, 4]
    assert o.loc["000000", "v3b"] - o.loc["000001", "v3b"] >= 25          # 추세 꺾인 종목은 크게 밀림


def test_tie_break_fixed():
    x = _x(4)
    x["atr_pct"] = [0.02, 0.019, 0.02, 0.02]
    x["value_ma20"] = [5e9, 5e9, 9e9, 5e9]
    o = v3.score(x, pd.Series(False, index=x.index), pd.DataFrame(), {})
    o["v3b"] = 40.0; o["fin25"] = 10.0                          # 완전 동점
    order = list(v3.top(o, 4, x=x).index)
    assert order == ["000001", "000002", "000000", "000003"]   # ATR% 낮은 순 → 거래대금 큰 순 → 코드


def _prices(n_days=60, codes=("A", "B", "C")):
    d = pd.bdate_range("2026-01-05", periods=n_days)
    C = pd.DataFrame({c: 1000.0 * (1 + 0.01 * k) ** np.arange(n_days) for k, c in enumerate(codes)}, index=d)
    return C.copy(), C, d


def test_simulate_hold_and_extend():
    O, C, d = _prices()
    r = v3.simulate({d[0]: ["A", "B"]}, O, C)
    t = pd.DataFrame(r.trades)
    assert set(t.code) == {"A", "B"}
    assert (t.exit == d[20].strftime("%Y-%m-%d")).all()       # 다음 날(d1) 매수 → 그날 포함 20거래일째 = d20
    assert abs(t.set_index("code").ret["B"] - (1.01 ** 19 * 0.9975 / 1.0015 - 1)) < 1e-6   # 비용 포함
    r2 = v3.simulate({d[0]: ["A"], d[10]: ["A"]}, O, C)       # 보유 중 다시 선정 → 연장, 추가매수 없음
    t2 = r2.trades[0]
    assert t2["exit"] == d[30].strftime("%Y-%m-%d") and t2["extends"] == 1 and len(r2.trades) == 1


def test_simulate_max_positions_and_weight():
    codes = [f"C{i:02d}" for i in range(25)]
    O, C, d = _prices(30, codes)
    r = v3.simulate({d[0]: codes}, O, C, end=d[1])
    assert len(r.holdings) == 20                                # 최대 20종목
    assert all(abs(h["weight"] - 0.05) < 0.01 for h in r.holdings)   # 종목당 약 5%


def test_calendar():
    cal = v3.calendar(pd.bdate_range("2026-09-01", "2026-10-08"), ahead=10)
    assert "2026-10-09" not in cal and "2026-10-12" in cal     # 한글날 휴장
    assert v3.nth_day(cal, "2026-10-12", 1) == "2026-10-12"
    td = pd.bdate_range("2026-10-01", "2026-10-08")
    assert v3.is_entry_day(td, "2026-10-01", "2026-10-01") and not v3.is_entry_day(td, "2026-10-01", "2026-10-02")
    assert v3.is_entry_day(td, "2026-10-01", "2026-10-08")     # 1,2,5,6,7 → 8일이 6번째 거래일 = 다음 선정일
    assert v3.next_entry_day(pd.bdate_range("2026-10-01", "2026-10-02"), "2026-10-01", "2026-10-02") == "2026-10-08"


def test_review_v3_sell_dates():
    from stockeye.portfolio import review
    cal = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2026-09-01", "2026-11-30")]
    x = pd.DataFrame({"close": [1000.0, 2000.0], "ret1": [0.01, 0.0], "low": [990.0, 1990.0], "high": [1010.0, 2010.0]},
                     index=["A", "B"])
    holds = [{"id": 1, "code": "A", "avg_price": 900, "qty": 10, "buy_date": "2026-09-01", "stop": 950},
             {"id": 2, "code": "B", "avg_price": 2000, "qty": 1, "buy_date": "2026-09-24"}]
    r = {h["code"]: h for h in review(holds, x, "2026-10-19", {"A": {"score": 40}}, calendar=cal)}
    assert r["A"]["sell_date"] == "2026-09-28" and r["A"]["status"] == "매도 예정일"        # 9/1 포함 20거래일째
    assert "연장" in r["A"]["alerts"][0] and "손절" not in " ".join(r["A"]["alerts"])       # V3: 손절 알림 없음
    assert r["B"]["sell_date"] == "2026-10-21" and r["B"]["status"] == "매도 임박" and r["B"]["days_left"] == 2
