from stockeye.analysis import surge_live as sl


ITEMS = [{"code": "A", "name": "가", "rank": 1, "score": 5.0, "close": 1000.0, "reasons": ["거래대금 3.0배"]},
         {"code": "B", "name": "나", "rank": 2, "score": 4.0, "close": 2000.0, "reasons": []}]


def test_stage():
    assert sl.stage(29.9, 29.9) == "상한가"
    assert sl.stage(22, 29.9) == "상한가 풀림"
    assert sl.stage(5, 21) == "+20% 돌파"
    assert sl.stage(-4, 1) == "하락" and sl.stage(1, 2) == "대기" and sl.stage(4, 5) == "상승 중"


def test_update_first_times_once():
    w = sl.SurgeWatch(ITEMS, "2026-11-02", "2026-11-03")
    q1 = [{"code": "A", "open": 1020, "high": 1160, "low": 1010, "close": 1150}, {"code": "B", "open": 2000, "high": 2010, "low": 1950, "close": 1990}]
    new = w.update(q1, "09:10")
    assert [(i["code"], l) for i, l in new] == [("A", "+15%"), ("A", "+10%")] or {l for _, l in new} == {"+15%", "+10%"}
    q2 = [{"code": "A", "open": 1020, "high": 1300, "low": 1010, "close": 1300}, {"code": "B", "open": 2000, "high": 2010, "low": 1950, "close": 1990}]
    new2 = w.update(q2, "09:20")
    assert {l for _, l in new2} == {"+20%", "상한가 도달"}               # 이미 닿은 레벨은 다시 안 나옴
    p = w.payload("09:20")
    assert p["reached"] == 1 and p["locked"] == 1 and p["rows"][0]["first"]["h10"] == "09:10"


def test_update_missing_quote():
    w = sl.SurgeWatch(ITEMS, "2026-11-02", "2026-11-03")
    w.update([], "09:01")
    assert w.rows[0]["status"] == "시세 없음"


def test_morning_text():
    p = {"items": [{"rank": 1, "name": "가"}], "stats": {"all": {"n": 40, "reached": 5.0, "closed": 2.5}, "days": 2, "base_lu": 0.4},
         "prev": {"date": "2026-11-02", "next": "2026-11-03", "n": 20, "reached": 10.0, "closed": 5.0, "h15": 15.0, "h20": 10.0,
                  "close_avg": 1.2, "base_close": 0.3, "base_lu": 0.4, "lu_total": 12, "lu_in20": 1, "lu_in100": 4,
                  "missed": [{"name": "다", "rank": None}, {"name": "라", "rank": 55}]}}
    t, b = sl.morning_text(p)
    assert "아침" in t and "상한가 닿음 10.0%" in b and "다(100위 밖)" in b and "1.가" in b
    t2, b2 = sl.morning_text({"items": [], "prev": None})
    assert "아직 없음" in b2
