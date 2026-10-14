import pandas as pd

from stockeye.analysis import flow_live as fl


def test_parse_latest_slot():
    js = {"output2": [{"bsop_hour_gb": "1", "frgn_fake_ntby_qty": "100", "orgn_fake_ntby_qty": "-50"},
                      {"bsop_hour_gb": "3", "frgn_fake_ntby_qty": "1,000", "orgn_fake_ntby_qty": "-200"},
                      {"bsop_hour_gb": "", "frgn_fake_ntby_qty": "", "orgn_fake_ntby_qty": ""}]}
    assert fl.parse(js) == (1000.0, -200.0, "11:20")
    assert fl.parse({"output2": []}) is None


def test_due_and_eok():
    assert fl.due_slot("09:34") is None
    assert fl.due_slot("09:35") == "09:30"
    assert fl.due_slot("13:30") == "13:20"
    assert fl.to_eok(100_000, 50_000) == 50.0
    assert fl.to_eok(1, None) is None


class K:
    def __init__(self):
        self.n = 0
        self.gb = "1"

    def _get(self, path, tr, params):
        self.n += 1
        return {"output2": [{"bsop_hour_gb": self.gb, "frgn_fake_ntby_qty": "200000", "orgn_fake_ntby_qty": "-100000"}]}


def test_run_once_per_slot_and_retry():
    k = K()
    f = fl.FlowLive(None, k, lambda cs: {c: 10_000 for c in cs})
    now = pd.Timestamp("2026-10-15 09:36")
    assert f.run(now, ["A", "B"]) == 2
    assert f.flows["A"] == [20.0, -10.0, "09:30"]
    assert f.run(now, ["A", "B"]) == 0                       # 같은 갱신분은 다시 안 받음
    assert f.run(now, ["A", "B", "C"]) == 1                   # 새 종목만
    later = pd.Timestamp("2026-10-15 10:06")                  # 10:00 분이 아직 안 나옴 → 최대 3번
    assert f.run(later, ["A"]) == 1
    assert f.run(later, ["A"]) == 1
    assert f.run(later, ["A"]) == 1
    assert f.run(later, ["A"]) == 0
    k.gb = "2"
    assert f.run(pd.Timestamp("2026-10-15 11:26"), ["A"]) == 1
