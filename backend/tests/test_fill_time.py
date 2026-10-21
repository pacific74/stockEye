import pandas as pd

from stockeye.analysis import rec_eval as re_
from stockeye.analysis.fill_time import first_touch


def _m(rows):
    return pd.DataFrame([{"time": pd.Timestamp(f"2026-10-21 {t}"), "open": o, "low": lo} for t, o, lo in rows])


def test_first_touch_open_inside_zone():
    assert first_touch(_m([("09:00", 99, 98), ("09:01", 100, 97)]), 100) == "09:00"


def test_first_touch_later_minute():
    assert first_touch(_m([("09:00", 105, 103), ("09:01", 103, 102), ("10:35", 102, 99)]), 100) == "10:35"


def test_first_touch_none():
    assert first_touch(_m([("09:00", 105, 103)]), 100) is None


def test_hour_bucket():
    assert re_.hour_bucket("10:35") == "10" and re_.hour_bucket("08:59") == "09" and re_.hour_bucket(None) == "--"


def test_grid_hour():
    rows = [
        {"rec_date": "2026-10-20", "kind": "v3", "code": "A", "score": 85, "res_status": "1차 목표", "res_done": True,
         "res_pnl": 3.0, "res_days": 2},
        {"rec_date": "2026-10-20", "kind": "v3", "code": "B", "score": 85, "res_status": "미체결", "res_done": True},
        {"rec_date": "2026-10-20", "kind": "limitcatch", "code": "C", "score": 72, "rec_time": "13:20",
         "res_status": "손절", "res_done": True, "res_pnl": -2.0, "res_days": 1},
    ]
    g = re_.grid_hour(rows, {"2026-10-20|v3|A": "10:35"})["2026-10-20"]
    assert g["10|80|v3"]["d"]["f"] == 1 and g["10|80|v3"]["d"]["t1"] == [1, 2]
    assert g["--|80|v3"]["d"]["n"] == 1 and g["--|80|v3"]["d"]["f"] == 0
    assert g["13|70|limitcatch"]["d"]["stop"] == [1, 1]
