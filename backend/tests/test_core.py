import pandas as pd
import pytest

from stockeye.config import load_config
from stockeye.data.pit import PointInTimeData, FutureDataError
from stockeye.data.sources.synthetic import generate
from stockeye.indicators import compute_features, rsi
from stockeye.engine.screener import screen, default_as_of
from stockeye.engine.trade_plan import tick_size, round_tick
from stockeye.backtest.costs import CostModel
from stockeye.backtest.engine import Backtester
from stockeye.backtest.strategy import RuleStrategy
from stockeye.backtest.lookahead import audit

CFG = load_config()


@pytest.fixture(scope="module")
def pit():
    g = generate(n_stocks=40, start="2022-01-03", end="2024-06-28", seed=1)
    return PointInTimeData(g["ohlcv"], g["flows"], g["fundamentals"], g["disclosures"], g["index"], g["listing"])


@pytest.fixture(scope="module")
def feat(pit):
    return compute_features(pit.ohlcv, pit.flows, pit.fund)


# ---------------- 미래참조 차단 (PIT) ----------------
def test_pit_hides_today_before_close(pit):
    d = pit.trading_dates()[200]
    v = pit.view(d + pd.Timedelta(hours=9, minutes=30))        # 09:30
    assert v.ohlcv()["date"].max() < d                         # 오늘 일봉은 아직 없음
    v2 = pit.view(d + pd.Timedelta(hours=15, minutes=30))      # 15:30 장 마감
    assert v2.ohlcv()["date"].max() == d
    assert v2.flows()["date"].max() < d                        # 수급은 18:00 이후 공개
    v3 = pit.view(d + pd.Timedelta(hours=18))
    assert v3.flows()["date"].max() == d


def test_pit_raises_on_future_request(pit):
    d = pit.trading_dates()[200]
    v = pit.view(d + pd.Timedelta(hours=9, minutes=30))
    with pytest.raises(FutureDataError):
        v.ohlcv(end=d)
    with pytest.raises(FutureDataError):
        v.flows(end=d + pd.Timedelta(days=1))


def test_disclosure_time_respected(pit):
    disc = pit.disc.iloc[0]
    before = pit.view(disc["published_at"] - pd.Timedelta(minutes=1)).disclosures(disc["code"])
    after = pit.view(disc["published_at"]).disclosures(disc["code"])
    assert disc["published_at"] not in before["published_at"].tolist()
    assert disc["published_at"] in after["published_at"].tolist()


def test_split_adjustment(pit, feat):
    """1:5 액면분할 날 가격은 -80% 이지만, 지표 수익률은 실제 등락률과 같아야 한다."""
    f = feat.reset_index()
    sp = f[f["split_factor"].round(4) != 1.0]
    assert not sp.empty, "합성 데이터에 분할 종목이 있어야 함"
    code = sp["code"].iloc[0]
    g = f[f["code"] == code].set_index("date")
    d = g.index[(g["split_factor"].diff().abs() > 1e-6)][0]
    raw = pit.ohlcv[(pit.ohlcv["code"] == code) & (pit.ohlcv["date"] == d)].iloc[0]
    assert abs(g.at[d, "ret1"] * 100 - raw["chg_pct"]) < 0.01
    assert g.at[d, "close"] / g.at[d, "sma20"] < 1.5      # 20일선도 분할 단위로 맞춰져 있음


# ---------------- 감사 ----------------
def test_audit_passes_for_causal_features(pit, feat):
    strat = RuleStrategy(["close_gt_sma20", {"vol_ratio_gte": 1.5}], CFG)
    rep = audit(pit, feat, strat, n_dates=3, n_codes=15)
    assert rep.passed, str(rep)


def test_audit_catches_lookahead_bug(pit):
    """일부러 '내일 종가'를 쓰는 버그를 심으면 감사가 잡아내야 한다."""
    def buggy(oh, fl, fd):
        f = compute_features(oh, fl, fd)
        f["sma20"] = f.groupby(level="code")["close"].shift(-1)   # 미래참조 버그!
        return f
    feat_bug = buggy(pit.ohlcv, pit.flows, pit.fund)
    rep = audit(pit, feat_bug, None, n_dates=3, n_codes=10, feature_fn=buggy)
    assert not rep.passed
    assert any("sma20" in c["detail"] for c in rep.checks if not c["passed"])


# ---------------- 엔진 ----------------
def test_screen_runs(pit):
    res = screen(pit.view(default_as_of(pit.trading_dates()[-1])), CFG)
    assert res.funnel[0][1] == 40
    for c in res.candidates:
        p = c.plan
        assert 0 <= c.score <= 100
        assert p["stop"] < p["price"] < p["target1"] < p["target2"]
        assert p["entry_low"] <= p["price"] <= p["entry_high"]


def test_tick():
    assert tick_size(1_999) == 1 and tick_size(32_500) == 50 and tick_size(600_000) == 1000
    assert round_tick(32_523) == 32_500
    assert round_tick(4_997, "up") == 5_000


def test_rsi_bounds(pit):
    s = pit.ohlcv[pit.ohlcv["code"] == pit.ohlcv["code"].iloc[0]]["close"].reset_index(drop=True)
    r = rsi(s).dropna()
    assert ((r >= 0) & (r <= 100)).all()


# ---------------- 백테스트 ----------------
def test_costs():
    c = CostModel()
    px, paid = c.buy(10_000, 100, 1e11)
    assert px > 10_000 and paid > 1_000_000
    px2, got = c.sell(10_000, 100, 1e11)
    assert px2 < 10_000 and got < 1_000_000
    assert 0.2 < c.round_trip_pct() < 0.5


def test_backtest_order_and_costs(pit, feat):
    strat = RuleStrategy(["close_gt_sma20", {"vol_ratio_gte": 1.2}], CFG)
    res = Backtester(pit, CFG, feat).run(strat, start="2022-08-01")
    assert res.trades, "거래가 하나는 있어야 함"
    for t in res.trades:
        assert t.signal_date < t.entry_date <= t.exit_date
        assert t.net_ret < t.gross_ret       # 비용이 반드시 수익을 깎는다
    free = load_config(overrides={"costs": {"commission_rate": 0, "sell_tax_rate": 0,
                                            "slippage_bps": 0, "illiquid_slippage_bps": 0}})
    res0 = Backtester(pit, free, feat).run(strat, start="2022-08-01")
    assert res0.metrics["total_return_pct"] > res.metrics["total_return_pct"]
