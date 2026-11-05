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
    assert [x["code"] for x in out] == ["b", "a"]               # c 갭 과대 · d 갭 작음 · e 변동폭 작음 · f 거래대금 작음 / b 는 급등예상 가산
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
