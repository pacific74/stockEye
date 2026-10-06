from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from stockeye.config import load_config, deep_merge
from stockeye.trading.journal import Journal
from stockeye.trading.engine import TradingEngine, Quote
from stockeye.trading.analysis import analyze, ai_summary
from stockeye.trading.notify import Notifier


class SilentNotifier(Notifier):
    def __init__(self):
        super().__init__()
        self.tg_token = self.ntfy = None
        self.sent = []

    def send(self, title, body, priority="default", url=None):
        self.sent.append((title, body))


def cand(code="000001", price=10000):
    return {"code": code, "name": f"테스트{code}", "score": 85.0, "stars": 4, "strategy": "A", "strategy_score": 80,
            "reasons": ["20일 이동평균선 상승", "거래량 2.1배 증가"], "warnings": [], "theme": "반도체",
            "plan": {"price": price, "entry_low": 9900, "entry_high": 10050, "stop": 9500, "target1": 10900,
                     "target2": 11500, "rr1": 1.8, "verdict": "매수 고려", "loss_pct": -5, "target1_pct": 9}}


REPORT = {"date": "2026-10-02", "market": {"mood": "강세"}, "candidates": [cand()], "strategies": {}}
T = datetime(2026, 10, 5, 9, 45)


def make(mode, tmp_path, **tc):
    cfg = deep_merge(load_config(), {"trading": {"mode": mode, "broker": "paper", **tc}})
    n = SilentNotifier()
    return TradingEngine(cfg, Journal(tmp_path / "j.db"), REPORT, n), n


def test_alert_mode_only_notifies(tmp_path):
    eng, n = make("alert", tmp_path)
    ev = eng.tick({"000001": Quote("000001", 10000, prev_close=9900)}, T)
    assert ev and ev[0]["type"] == "entry" and not eng.j.positions()
    assert any("매수 신호" in t for t, _ in n.sent)
    assert not eng.tick({"000001": Quote("000001", 10000, prev_close=9900)}, T)   # 같은 날 중복 알림 없음


def test_no_signal_outside_zone_or_time(tmp_path):
    eng, _ = make("paper", tmp_path)
    assert not eng.tick({"000001": Quote("000001", 10300, prev_close=9900)}, T)            # 구간 위
    assert not eng.tick({"000001": Quote("000001", 10000, prev_close=9900)}, datetime(2026, 10, 5, 9, 2))  # 장 초반


def test_paper_round_trip_and_journal(tmp_path):
    eng, n = make("paper", tmp_path, position_krw=1_000_000)
    eng.tick({"000001": Quote("000001", 10000, prev_close=9900)}, T)
    pos = eng.j.positions(status="open")
    assert len(pos) == 1 and pos[0]["mode"] == "paper" and pos[0]["strategy"] == "A" and pos[0]["score"] == 85
    assert pos[0]["stop"] == 9500 and "거래량 2.1배 증가" in pos[0]["reasons"] and pos[0]["market_mood"] == "강세"
    cash = eng.j.cash("paper", 0)
    assert cash < 10_000_000
    # 손절가 한참 아래에서 체결 → 손절 지연 표시
    eng.tick({"000001": Quote("000001", 9300, low=9300, high=10000, prev_close=10000)}, datetime(2026, 10, 7, 10, 0))
    closed = eng.j.positions(status="closed")[0]
    assert closed["exit_reason"] == "손절" and closed["ret_pct"] < 0 and closed["result"] == "실패"
    assert closed["late_stop"] == 1 and closed["hold_days"] == 2 and closed["mae_pct"] < 0
    assert eng.j.cash("paper", 0) > cash


def test_semi_auto_approval(tmp_path):
    eng, n = make("semi_auto", tmp_path)
    ev = eng.tick({"000001": Quote("000001", 10000, prev_close=9900)}, T)
    oid = ev[0]["order_id"]
    assert eng.j.get_order(oid)["status"] == "pending" and not eng.j.positions()
    # 승인 시점에 가격이 손절가 아래면 주문하지 않음
    r = eng.approve(oid, Quote("000001", 9400))
    assert not r["ok"] and eng.j.get_order(oid)["status"] == "rejected"


def test_semi_auto_approve_buy_then_sell(tmp_path):
    eng, n = make("semi_auto", tmp_path)
    oid = eng.tick({"000001": Quote("000001", 10000, prev_close=9900)}, T)[0]["order_id"]
    r = eng.approve(oid, Quote("000001", 10010))
    assert r["ok"] and eng.j.positions(status="open")
    ev = eng.tick({"000001": Quote("000001", 11000, high=11000, low=10500, prev_close=10500)}, datetime(2026, 10, 8, 11, 0))
    sell_oid = ev[0]["order_id"]
    assert eng.j.positions(status="open")      # 승인 전에는 안 팖
    assert eng.approve(sell_oid, Quote("000001", 10950))["ok"]
    c = eng.j.positions(status="closed")[0]
    assert c["exit_reason"] == "목표가" and c["result"] == "성공" and c["signal_time"]
    assert eng.reject(sell_oid)["ok"] is False


def test_risk_limits(tmp_path):
    eng, n = make("paper", tmp_path, max_daily_buys=0)
    ev = eng.tick({"000001": Quote("000001", 10000, prev_close=9900)}, T)
    assert ev[0]["blocked"] and not eng.j.positions()


def test_analysis(tmp_path):
    j = Journal(tmp_path / "a.db")
    rng = np.random.default_rng(1)
    for i in range(240):
        s = "ABCD"[i % 4]
        h = ["09:10", "09:50", "13:00", "14:30"][i % 4 if i % 3 else (i + 1) % 4]
        edge = {"A": 1.0, "B": 0.5, "C": -1.5, "D": 1.5}[s]
        c = cand(f"{i:06d}")
        c["strategy"], c["score"] = s, float(rng.uniform(60, 95))
        pid = j.open_position("paper", c["code"], 10000, 10, cand=c, entry_time=f"2026-0{1 + i % 9}-1{i % 10} {h}:00",
                              market_mood=["강세", "중립", "약세"][i % 3])
        ret = rng.normal(edge, 4)
        px = 10000 * (1 + ret / 100)
        j.close_position(pid, px, reason="손절" if ret < 0 else "목표가", exit_time=f"2026-0{1 + i % 9}-2{i % 8} 14:00")
    a = analyze(j.frame(), min_n=20)
    assert a["closed"] == 240
    names = {g["group"]: g for g in a["by_strategy"]}
    assert names["급등추격"]["avg_ret"] < names["수급매매"]["avg_ret"]
    assert a["insights"] and any("전략" in s for s in a["insights"])
    assert "late_stop" in a["diagnostics"]
    s = ai_summary(a, load_config())
    assert s["text"]


def test_analysis_small_sample_flag(tmp_path):
    j = Journal(tmp_path / "s.db")
    pid = j.open_position("manual", "000001", 10000, 1, cand=cand())
    j.close_position(pid, 10500, reason="수동")
    a = analyze(j.frame())
    assert a["closed"] == 1 and all(g["low_confidence"] for g in a["by_strategy"])
    assert any("이릅" in s for s in a["insights"])


def test_collect_program_with_fake_kis(tmp_path, monkeypatch):
    """KIS 프로그램매매 수집 경로 (가짜 클라이언트) — import 경로/단위 판별/저장 확인."""
    from stockeye.data.store import DataStore
    from stockeye.data.sources.synthetic import generate
    from stockeye.data.sources import kis_source
    store = DataStore(tmp_path)
    for k, v in generate(n_stocks=20, start="2025-01-02", end="2025-06-30").items():
        store.save(k, v)

    class FakeKIS:
        def __init__(self, *a, **k):
            pass

        def program_daily(self, code):
            d = pd.bdate_range("2025-06-02", "2025-06-30")
            return pd.DataFrame({"date": d, "code": code, "program_raw": 1.5, "gross_raw": 10.0, "value_raw": 100e6})

    monkeypatch.setattr(kis_source, "KISClient", FakeKIS)
    cfg = deep_merge(load_config(), {"data": {"dir": str(tmp_path)}, "stage1": {"min_trading_value": 0}})
    df = kis_source.collect_program(store, cfg)
    assert not df.empty and set(store.load("program").columns) >= {"date", "code", "program"}
    assert df["program"].iloc[0] == 1.5 * 1e6     # 백만원 단위로 판별
