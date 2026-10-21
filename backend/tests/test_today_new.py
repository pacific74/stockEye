from stockeye.cloud.today_new import mark


def _r(codes, tabs=None):
    return {"candidates": [{"code": c} for c in codes],
            "strategies": {k: {"candidates": [{"code": c} for c in v]} for k, v in (tabs or {}).items()}}


def test_marks_only_new_codes():
    prev = _r(["A", "B"], {"early": ["A"]})
    cur = _r(["A", "C"], {"early": ["A", "D"], "v3": ["X"]})
    assert mark(cur, prev) == 2
    assert [c.get("today_new") for c in cur["candidates"]] == [None, True]
    assert [c.get("today_new") for c in cur["strategies"]["early"]["candidates"]] == [None, True]
    assert "today_new" not in cur["strategies"]["v3"]["candidates"][0]      # 어제 없던 탭은 표시 안 함


def test_second_intraday_keeps_earlier_marks():
    evening = _r(["A"])
    at11 = _r(["A", "C"]); mark(at11, evening)
    at14 = _r(["A", "C", "E"]); assert mark(at14, at11) == 2
    assert [c.get("today_new") for c in at14["candidates"]] == [None, True, True]


def test_no_prev_no_marks():
    cur = _r(["A"]); assert mark(cur, None) == 0 and "today_new" not in cur["candidates"][0]
