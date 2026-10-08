"""매수후보 V2: 공시 규칙 · 재무 지표 · 점수/차단/신호."""
import numpy as np
import pandas as pd

from stockeye.config import load_config
from stockeye.data.financials import FinIndex, build_metrics
from stockeye.engine.disclosure_rules import DisclosureIndex, classify
from stockeye.engine.v2 import V2Context, evaluate, market_states, grade_of

CFG = load_config()


def test_disclosure_classify_and_blocks():
    assert classify("단일판매ㆍ공급계약체결")[1] > 0
    assert classify("유상증자결정(제3자배정)")[1] < 0 and classify("유상증자결정(제3자배정)")[3] is None
    assert classify("유상증자결정(주주배정)")[3] == "대규모 유상증자"
    assert classify("횡령ㆍ배임혐의발생")[3] == "횡령·배임"
    assert classify("[기재정정]단일판매ㆍ공급계약체결")[0] == "수주"
    assert classify("임원ㆍ주요주주특정증권등소유상황보고서") is None
    d = pd.DataFrame({
        "code": ["A", "A", "A", "B", "B"],
        "published_at": pd.to_datetime(["2024-01-02 23:59", "2024-01-03 23:59", "2024-01-05 23:59",
                                        "2024-01-02 23:59", "2024-03-02 23:59"]),
        "title": ["단일판매ㆍ공급계약체결", "단일판매ㆍ공급계약체결", "전환사채권발행결정",
                  "관리종목지정", "관리종목지정해제"]})
    ix = DisclosureIndex.build(d)
    a = ix.at("A", pd.Timestamp("2024-01-10 18:00"))
    assert a["score"] == 7 + 4 - 4 and a["block"] == []            # 수주는 한 번만
    assert ix.at("A", pd.Timestamp("2024-01-03 18:00"))["score"] == 7 + 4   # 미래 공시(1/3 23:59)는 안 보임
    assert ix.at("B", pd.Timestamp("2024-02-01 18:00"))["block"] == ["관리종목"]
    assert ix.at("B", pd.Timestamp("2024-03-10 18:00"))["block"] == []      # 해제


def test_financial_metrics_pit():
    rows = []
    for y, rev, op in ((2022, 100, 10), (2023, 130, 15)):
        rows.append({"code": "A", "year": y, "reprt": "FY", "fs": "CFS", "revenue": rev, "op_income": op,
                     "net_income": op * 0.8, "assets": 300, "liabilities": 100, "equity": 200, "capital": 50,
                     "cur_assets": 120, "cur_liab": 60, "date": pd.Timestamp(f"{y + 1}-03-15 23:59")})
    m = build_metrics(pd.DataFrame(rows))
    r = m[m["year"] == 2023].iloc[0]
    assert abs(r["rev_yoy"] - 0.3) < 1e-9 and r["op_improve"] and r["debt_ratio"] == 0.5 and not r["impaired"]
    fi = FinIndex(m)
    assert fi.at(["A"], pd.Timestamp("2024-03-15 18:00")).loc["A", "year"] == 2022   # 2023 사업보고서는 아직
    assert fi.at(["A"], pd.Timestamp("2024-03-16 18:00")).loc["A", "year"] == 2023


def _x(n=3):
    idx = [f"00000{i}" for i in range(n)]
    base = dict(close=10000.0, sma20=9900.0, sma60=9500.0, sma120=9000.0, sma20_slope=0.01, sma60_slope=0.01,
                ret20=0.05, ret60=0.1, ret5=0.02, vol5_ratio=1.2, updown_vol20=1.5, value_ma20=2e10,
                value_ratio=1.2, foreign_net5=1e8, foreign_net20=2e8, institution_net5=1e8, institution_net20=1e8,
                individual_net5=-2e8, foreign_streak=3, institution_streak=1, low20=9600.0, atr14=200.0,
                dist_sma20=0.01, touch_sma20_3d=1.0, up_day=True, vol_ratio=1.3, high20_prev=10500.0,
                atr_pct=0.02, near_high250=0.9, rsi14=60.0, halted=False, per=10.0, pbr=1.0)
    return pd.DataFrame([base] * n, index=idx)


def test_evaluate_signal_and_blocks():
    x = _x(3)
    x.loc["000001", "value_ma20"] = 1e9                 # 거래대금 부족 → 차단
    x.loc["000002", ["ret5", "ret20"]] = [0.3, 0.6]     # 과열
    dates = pd.bdate_range("2023-01-02", periods=260)
    idx = pd.DataFrame({"date": dates, "code": "KOSPI", "close": np.linspace(2000, 2600, 260)})
    ctx = V2Context(dates[-1], {c: "KOSPI" for c in x.index}, market_states(idx))
    ev = evaluate(x, ctx, CFG)
    assert ev.loc["000000", "market_state"] == "A"
    assert ev.loc["000000", "score"] >= 75 and ev.loc["000000", "signal"]
    assert ev.loc["000001", "status"] == "매수 차단" and "거래대금 부족" in ev.loc["000001", "blocks"]
    assert ev.loc["000002", "status"] == "과열 — 관망" and not ev.loc["000002", "signal"]
    assert set(ev.columns) >= {"trend", "volume", "value", "flow", "position", "risk", "financial", "news", "grade"}
    # 하락장이면 신규 매수 중단
    idx2 = pd.DataFrame({"date": dates, "code": "KOSPI", "close": np.linspace(2600, 2000, 260)})
    ev2 = evaluate(x, V2Context(dates[-1], {c: "KOSPI" for c in x.index}, market_states(idx2)), CFG)
    assert ev2.loc["000000", "market_state"] == "C" and not ev2["signal"].any()
    assert grade_of(86)[0] == "강력 후보" and grade_of(54)[0] == "제외"
