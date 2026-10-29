from stockeye.analysis import shortlist as sl


def _r(code, score, status="관찰", typ="눌림목", ex=None):
    return {"code": code, "name": code, "score": score, "status": status, "type": typ, "excluded": ex or [], "warnings": []}


def test_pick_skips_excluded_and_sorts():
    res = [_r("a", 80), _r("b", 95, ex=["x"]), _r("c", 90), _r("d", 70)]
    assert [x["code"] for x in sl.pick(res, 2)] == ["c", "a"]
    assert sl.pick(res, 2)[0]["rank"] == 1


def test_freeze_only_after_0910_once():
    st = sl.new_state()
    res = [_r("a", 80), _r("b", 90)]
    assert not sl.freeze(st, res, "09:09") and not sl.frozen(st)
    assert sl.freeze(st, res, "09:10") and sl.frozen(st)
    assert not sl.freeze(st, [_r("z", 99)], "09:30")                 # 한 번 고정하면 그대로
    assert [x["code"] for x in st["list"]] == ["b", "a"]


def test_gate_before_freeze_and_outside_list():
    st = sl.new_state()
    r = _r("a", 85, "진입 조건 충족")
    sl.gate(r, st)
    assert r["status"] == "진입 대기" and "선별" in r["warnings"][0]
    sl.freeze(st, [_r(f"c{i}", 99 - i) for i in range(12)] + [_r("a", 85)], "09:10")
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
    sl.freeze(st, [_r("a", 85)], "09:10")
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
            return [{"payload": {"date": self.day, "shortlist": {"at": "09:10", "list": [{"code": "a", "rank": 1}], "late": ["z"]}}}]
    assert sl.restore(SB("2026-10-29"), "2026-10-29")["list"][0]["code"] == "a"
    assert not sl.frozen(sl.restore(SB("2026-10-28"), "2026-10-29"))
    assert not sl.frozen(sl.restore(None, "2026-10-29"))
