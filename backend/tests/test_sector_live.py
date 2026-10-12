from scripts.sector_live import compute, members_of


def test_weighted_all_members_and_fallback():
    m = members_of([{"group": "A", "live": [{"code": "1", "w": 0.5}, {"code": "2", "w": 0.3}, {"code": "3", "w": 0.2}]},
                    {"group": "B", "top": [{"code": "1"}, {"code": "2"}, {"code": "4"}]}])
    out = compute(m, {"1": 2.0, "2": -1.0, "3": 0.0, "4": 1.0}, {"A": "sector"})
    a = next(g for g in out if g["group"] == "A")
    assert a["chg_pct"] == 0.7 and a["n"] == 3 and a["up"] == 1          # 0.5*2 + 0.3*-1 + 0.2*0
    assert out[0]["group"] == "A"                                          # 높은 순
