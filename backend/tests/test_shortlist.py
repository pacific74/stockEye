from stockeye.analysis import shortlist as sl


def _r(code, score, status="관찰", typ="눌림목", ex=None):
    return {"code": code, "name": code, "score": score, "status": status, "type": typ, "excluded": ex or [], "warnings": []}


def test_pick_skips_excluded_and_sorts():
    res = [_r("a", 80), _r("b", 95, ex=["x"]), _r("c", 90), _r("d", 70)]
    assert [x["code"] for x in sl.pick(res, 2)] == ["c", "a"]
    assert sl.pick(res, 2)[0]["rank"] == 1


def test_freeze_only_after_0905_once():
    st = sl.new_state()
    res = [_r("a", 80), _r("b", 90)]
    assert not sl.freeze(st, res, "09:04") and not sl.frozen(st)
    assert sl.freeze(st, res, "09:05") and sl.frozen(st)
    assert not sl.freeze(st, [_r("z", 99)], "09:30")                 # 한 번 고정하면 그대로
    assert [x["code"] for x in st["list"]] == ["b", "a"]


def test_gate_before_freeze_and_outside_list():
    st = sl.new_state()
    r = _r("a", 85, "진입 조건 충족")
    sl.gate(r, st)
    assert r["status"] == "진입 대기" and "선별" in r["warnings"][0]
    sl.freeze(st, [_r(f"c{i}", 99 - i) for i in range(12)] + [_r("a", 85)], "09:05")
    r = _r("a", 85, "진입 조건 충족")
    sl.gate(r, st)
    assert r["status"] == "진입 대기" and "밖" in r["warnings"][0]          # 후보 밖
    r = _r("c1", 98, "진입 조건 충족")
    sl.gate(r, st)
    assert r["status"] == "진입 조건 충족"                                 # 후보 안
    sl.tag(r, st)
    assert r["cand_rank"] == 2


def test_gate_late_add_and_types(monkeypatch):
    st = sl.new_state()
    sl.freeze(st, [_r("a", 85)], "09:05")
    r = _r("x", 91, "진입 조건 충족")
    sl.gate(r, st)
    assert r["status"] == "진입 조건 충족" and "x" in st["late"]
    sl.tag(r, st)
    assert r["cand_rank"] == 0
    monkeypatch.setattr(sl, "TYPES", ("눌림목",))
    r = _r("a", 85, "진입 조건 충족", typ="돌파")
    sl.gate(r, st)
    assert r["status"] == "진입 대기"


def test_restore_same_day_only():
    class SB:
        def __init__(self, day):
            self.day = day

        def select(self, t, q):
            return [{"payload": {"date": self.day, "shortlist": {"at": "09:05", "list": [{"code": "a", "rank": 1}], "late": ["z"]}}}]
    assert sl.restore(SB("2026-10-29"), "2026-10-29")["list"][0]["code"] == "a"
    assert not sl.frozen(sl.restore(SB("2026-10-28"), "2026-10-29"))
    assert not sl.frozen(sl.restore(None, "2026-10-29"))


def test_early_pick_filters_and_boost():
    pre = {"a": [1100, 8.0], "b": [1100, 5.0], "c": [1100, 30.0], "d": [1100, 1.0], "e": [1100, 6.0], "f": [1100, 4.0]}
    info = {"a": {"adr": 0.08, "pv": 5e9, "name": "A"}, "b": {"adr": 0.09, "pv": 5e9, "name": "B"},
            "c": {"adr": 0.09, "pv": 5e9}, "d": {"adr": 0.09, "pv": 5e9},
            "e": {"adr": 0.03, "pv": 5e9}, "f": {"adr": 0.09, "pv": 1e9}}
    out = sl.early_pick(pre, info, {"b"})
    assert [x["code"] for x in out if x["tier"] == 1] == ["b", "a"]   # 기본 기준: c 갭 과대 · d 갭 작음 · e 변동폭 작음 · f 거래대금 작음 / b 는 급등예상 가산
    assert "c" not in [x["code"] for x in out]                       # 갭 과대(+25% 초과)는 기준을 풀어도 제외
    assert out[0]["surge"] and "key" not in out[0]


def test_freeze_combines_early_and_top_score():
    st = sl.new_state()
    st["early"] = [{"code": "e1", "name": "E1", "pre": 6.0}, {"code": "e2", "name": "E2", "pre": 4.0}]
    res = [_r("e1", 70), _r(f"s{0}", 95)] + [_r(f"s{i}", 90 - i) for i in range(1, 12)]
    assert sl.freeze(st, res, "09:05")
    codes = [x["code"] for x in st["list"]]
    assert len(codes) == sl.N and {"e1", "e2"} <= set(codes)         # 선발 2 + 점수 상위 8
    assert codes[0] == "s0" and codes[-1] == "e2"                     # 점수 순, 점수 없는 선발은 맨 뒤
    assert [x["rank"] for x in st["list"]] == list(range(1, sl.N + 1))
    r = _r("e1", 70)
    sl.tag(r, st)
    assert r["early"] and r["cand_rank"] >= 1


def test_tag_early_before_freeze():
    st = sl.new_state()
    st["early"] = [{"code": "e1", "name": "E1"}]
    r = _r("e1", 50)
    sl.tag(r, st)
    assert r["cand_rank"] == 0 and r["early"]
    assert sl.view(st)["early"][0]["code"] == "e1"


def test_early_pick_after_market_and_flow():
    pre = {"a": [1000, 0.5], "b": [1000, 4.0], "c": [1000, -2.0]}
    after = {"a": [1000, 6.0], "b": [1000, 2.0], "c": [1000, 7.0], "z": [1000, 9.0]}
    info = {k: {"adr": 0.08, "pv": 5e9, "name": k} for k in "abcz"}
    out = sl.early_pick(pre, info, after=after, flow={"a": 0.10})
    codes = [x["code"] for x in out]
    assert "c" not in codes                              # 애프터는 올랐지만 프리마켓이 0% 미만이면 제외
    assert codes[0] == "z" or codes[0] == "a"
    a = next(x for x in out if x["code"] == "a")
    assert a["after"] == 6.0 and a["flow"] == 5.0        # 수급 가산은 최대 5
    assert a["score"] == round(0.5 + 3.0 + 5.0, 1)


def test_types_allow_breakout_by_default():
    st = sl.new_state()
    sl.freeze(st, [_r("a", 85)], "09:05")
    r = _r("a", 85, "진입 조건 충족", typ="돌파")
    sl.gate(r, st)
    assert r["status"] == "진입 조건 충족"               # 2026-11-05: 돌파형도 허용 (조건별 확률 비교용)
    r["early_info"] = None
    st["early"] = [{"code": "a", "pre": 5.0, "after": 3.0}]
    sl.tag(r, st)
    assert r["early_info"] == {"pre": 5.0, "after": 3.0}


def test_early_pick_fills_five_by_relaxing_and_uses_open_gap():
    info = {f"x{i}": {"adr": 0.04, "pv": 2e9, "name": f"X{i}"} for i in range(8)}      # 기본 기준(변동폭 5%·30억)은 모두 탈락
    info["g"] = {"adr": 0.09, "pv": 9e9, "name": "G"}
    pre = {f"x{i}": [1000, 2.0 + i * 0.1] for i in range(8)}
    out = sl.early_pick(pre, info, live={"g": 12.0})
    assert len(out) == 5 and out[0]["code"] == "g" and out[0]["tier"] == 1 and out[0]["open"] == 12.0   # 시초 갭만 있는 종목도 잡힘
    assert all(x["tier"] >= 2 for x in out[1:])                                         # 나머지는 기준을 풀어 채움


def test_vol_surge_ratio_and_min_prev():
    out = sl.vol_surge({"a": 31000, "b": 29000, "c": 90000, "d": 5000}, {"a": 10000, "b": 10000, "c": 500, "d": 1000}, {"a": "A"})
    assert [x["code"] for x in out] == ["d", "a"]        # 비율 큰 순 · b 290% 미만 · c 전일 거래량 너무 적음
    assert out[1]["vr"] == 310 and out[1]["name"] == "A"


def test_freeze_uses_vol_surge_pool_and_falls_back():
    res = [_r(f"s{i}", 90 - i) for i in range(12)]
    st = sl.new_state()
    st["early"] = [{"code": "e1", "name": "E1", "pre": 5.0}]
    st["vs"] = [{"code": "s3", "vr": 450}, {"code": "s7", "vr": 320}, {"code": "e1", "vr": 999}]
    assert sl.freeze(st, res, "09:05")
    codes = [x["code"] for x in st["list"]]
    assert set(codes) == {"e1", "s3", "s7"}                  # 거래량 300%↑ 풀에 없는 종목은 점수가 높아도 제외
    assert next(x for x in st["list"] if x["code"] == "s3")["src"] == "vol"
    st2 = sl.new_state()                                     # 거래량 비교를 못 했으면 (vs None) 예전처럼 점수 상위
    assert sl.freeze(st2, res, "09:05") and len(st2["list"]) == sl.N
    assert all(x["src"] == "score" for x in st2["list"])


def test_add_surge_replaces_excluded_and_goes_last():
    res = [_r(f"s{i}", 90 - i) for i in range(12)]
    for r in res:
        r["excluded"] = False
    st = sl.new_state()
    sl.freeze(st, res, "09:05")
    names = {r["code"] for r in st["list"]}
    bad = st["list"][3]["code"]
    byc = {r["code"]: r for r in res}
    byc[bad]["excluded"] = True                                   # 후보 중 하나가 진입 금지가 됨
    res.append({**_r("hot", 70), "excluded": False})
    ch = sl.add_surge(st, ["hot", "none"], res, {"hot": "급등주"}, set())
    assert ch == [{"add": "hot", "removed": bad}]
    codes = [x["code"] for x in st["list"]]
    assert codes[-1] == "hot" and bad not in codes and len(codes) == sl.N       # 진입 금지 자리에 맨 뒤로
    assert [x["rank"] for x in st["list"]] == list(range(1, sl.N + 1)) and st["list"][-1]["src"] == "surge"
    assert sl.add_surge(st, ["hot"], res, {}, set()) == []                       # 두 번 넣지 않음
    # 진입 금지가 없으면 N 을 넘겨 붙임 (최대 N+5) · 급등 종목 자신이 진입 금지면 건너뜀
    byc[bad]["excluded"] = False
    res += [{**_r(f"h{i}", 60), "excluded": False} for i in range(7)] + [{**_r("bad", 99), "excluded": True}]
    sl.add_surge(st, [f"h{i}" for i in range(7)] + ["bad"], res, {}, set())
    assert len(st["list"]) == sl.N + sl.SURGE_EXTRA and "bad" not in [x["code"] for x in st["list"]]


def test_volume_rank_parse_and_score_weights():
    import pandas as pd
    from stockeye.data.sources.kis_source import KISClient
    from stockeye.engine import daytrade as dt
    k = KISClient.__new__(KISClient)
    k._get = lambda *a, **kw: {"output": [{"mksc_shrn_iscd": "5930", "hts_kor_isnm": "A", "stck_prpr": "1000", "prdy_ctrt": "3.5",
                                           "acml_vol": "500000", "acml_tr_pbmn": "500000000", "vol_inrt": "420.5"}]}
    df = k.volume_rank("0001", "surge")
    assert df.loc[0, "code"] == "005930" and df.loc[0, "vol_inrt"] == 420.5
    assert sum(m for _, m in dt.PARTS.values()) == 100 and dt.PARTS["liq20"][1] == 10 and dt.PARTS["vol15"][1] == 25
    t = pd.date_range("2026-11-09 09:00", periods=40, freq="min")
    b = pd.DataFrame({"time": t, "open": 1000.0, "high": 1010.0, "low": 995.0, "close": 1005.0, "volume": 1000.0})
    ctx = {"name": "x", "prev_close": 990.0, "now": t[-1], "value": 3e9}
    lo = dt.evaluate(b, {**ctx, "vol_day": 0.1})["parts"]["vol15"]
    hi = dt.evaluate(b, {**ctx, "vol_day": 2.0})["parts"]["vol15"]
    assert hi > lo                                                  # 평소 대비 누적 거래량이 클수록 거래량 점수가 높음
    big = dt.evaluate(b, {**ctx, "value": 3e11})["parts"]["liq20"]
    mid = dt.evaluate(b, {**ctx, "value": 3e9})["parts"]["liq20"]
    assert big == mid                                               # 거래대금은 30억 이상이면 더 크다고 점수를 더 주지 않음


def test_minute_archive_includes_volume_leaders():
    import pandas as pd
    from stockeye.analysis import minute_archive as ma
    rows = [{"code": f"{i:06d}", "chg_pct": 0.0, "value": 5e9 if i < 150 else 2e9, "volume": 100.0 + i} for i in range(300)]
    snap = pd.DataFrame(rows)
    out = ma.pick(snap)
    assert "000299" in out and len(out) >= 150 + ma.TOP_VOLUME - 150    # 거래량 큰 종목(거래대금 20억)도 포함
