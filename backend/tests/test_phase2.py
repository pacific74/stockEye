import numpy as np
import pandas as pd
import pytest

from stockeye.config import load_config
from stockeye.data.pit import PointInTimeData
from stockeye.data.sources.synthetic import generate
from stockeye.indicators import compute_features
from stockeye.engine.strategies import STRATEGIES, select
from stockeye.engine.screener import screen, default_as_of, analyze_one
from stockeye.analysis.similar import PatternIndex
from stockeye.analysis.market import market_overview, build_groups, group_strength
from stockeye.ai.explainer import verify_numbers, rule_based, _payload, Explainer
from stockeye.backtest.engine import Backtester
from stockeye.backtest.strategy import NamedStrategy
from stockeye.backtest.lookahead import audit
from stockeye.portfolio import LocalRepo, review

CFG = load_config()


@pytest.fixture(scope="module")
def data():
    g = generate(n_stocks=60, start="2022-01-03", end="2024-12-30", seed=3)
    pit = PointInTimeData(g["ohlcv"], g["flows"], g["fundamentals"], g["disclosures"], g["index"], g["listing"])
    return g, pit


@pytest.fixture(scope="module")
def result(data):
    _, pit = data
    return screen(pit.view(default_as_of(pit.trading_dates()[-1])), CFG)


def test_strategies_run(result):
    assert set(result.strategies) == set(STRATEGIES)
    for k, lst in result.strategies.items():
        for c in lst:
            assert c.strategy == k and c.strategy_reasons
            assert c.plan["verdict"] in ("매수 고려", "눌림 대기", "관심", "관망")


def test_strategy_masks_dont_crash_on_missing_cols(result):
    x = result.universe.drop(columns=[c for c in result.universe.columns if c.startswith(("foreign", "institution", "eps", "per", "pbr"))])
    for k in STRATEGIES:
        select(k, x)


def test_named_strategy_backtest_and_audit(data):
    _, pit = data
    feat = compute_features(pit.ohlcv, pit.flows, pit.fund)
    strat = NamedStrategy("A", CFG)
    res = Backtester(pit, CFG, feat).run(strat, start="2023-01-01")
    for t in res.trades:
        assert t.signal_date < t.entry_date
    rep = audit(pit, feat, strat, res.trades, n_dates=2, n_codes=15)
    assert rep.passed, str(rep)


def test_similar_is_point_in_time(data):
    g, pit = data
    ix = PatternIndex(g["ohlcv"])
    as_of = pd.Timestamp("2024-06-28")
    code = g["ohlcv"]["code"].iloc[0]
    r = ix.search(code, as_of, top=10)
    assert "error" not in r
    dates = ix.dates
    for m in r["matches"]:
        end_i = dates.get_loc(pd.Timestamp(m["end"]))
        assert end_i + 20 <= dates.searchsorted(as_of, side="right") - 1   # 결과 구간까지 as_of 이전
    # as_of 이후 데이터를 바꿔도 결과가 같아야 함
    g2 = g["ohlcv"].copy()
    fut = g2["date"] > as_of
    g2.loc[fut, "chg_pct"] = np.random.default_rng(0).uniform(-29, 29, fut.sum())
    r2 = PatternIndex(g2).search(code, as_of, top=10)
    assert [m["code"] for m in r["matches"]] == [m["code"] for m in r2["matches"]]
    assert r["stats"] == r2["stats"]


def test_market_and_groups(data, result):
    _, pit = data
    view = pit.view(default_as_of(pit.trading_dates()[-1]))
    m = market_overview(view.index(), result.x)
    assert m["mood"] in ("강세", "중립", "약세")
    names = pit.listing
    themes = {"테스트": list(names["name"].iloc[:8])}
    groups, unmatched = build_groups(names, pd.DataFrame(), themes)
    s = group_strength(result.x, groups, {}, names, min_value=0)
    assert s and 0 <= s[0]["score"] <= 100 and not unmatched


def test_verify_numbers():
    payload = {"현재가": 32500, "손절가": 30900, "손익비": 1.88, "예상손실(%)": -4.9, "근거": ["거래량 2.1배 증가"]}
    ok, _ = verify_numbers("현재가 32,500원, 손절 30,900원, 손익비 1.88, 거래량 2.1배. 1차 목표를 본다.", payload)
    assert ok
    ok, bad = verify_numbers("목표가는 40,000원이 유력하다.", payload)
    assert not ok and "40,000" in bad


def test_rule_based_explanation(result):
    c = (result.candidates or [c for v in result.strategies.values() for c in v])[0].to_dict()
    txt = rule_based(c)
    assert len(txt) > 20
    ok, bad = verify_numbers(txt, _payload(c))
    assert ok, bad


def test_explainer_without_key(result, tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    c = result.candidates[0].to_dict()
    out = Explainer(CFG, tmp_path).explain(c, "2024-12-30")
    assert out["source"] == "rule" and out["text"]


def test_analyze_one(data):
    _, pit = data
    view = pit.view(default_as_of(pit.trading_dates()[-1]))
    code = pit.ohlcv["code"].iloc[0]
    c = analyze_one(view, code, CFG, pit.listing)
    assert c and c["plan"]["stop"] < c["plan"]["price"]


def test_portfolio_review(result, tmp_path):
    repo = LocalRepo(tmp_path / "p.json")
    code = result.x.index[0]
    px = float(result.x.loc[code, "close"])
    repo.add({"code": code, "name": "t", "qty": 10, "avg_price": px * 0.9, "stop": px * 1.5, "target": px * 0.5,
              "buy_date": "2024-11-01"})
    r = review(repo.list(), result.x, "2024-12-30")[0]
    assert r["pnl_pct"] > 0 and r["status"] == "손절 검토"
    assert any("목표가" in a for a in r["alerts"])
