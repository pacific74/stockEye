"""보유종목이 어느 관심 탭에서 산 것인지 (매수일 직전 기록) + 그때 매수구간·손절가"""
from stockeye.cloud import publish as pub

Z = [{"name": "1차", "low": 37500, "high": 38200, "weight": 30}, {"name": "2차", "low": 36800, "high": 37100, "weight": 30},
     {"name": "3차", "low": 35900, "high": 36200, "weight": 40}]


def _row(d, lst, stop=35000):
    return {"date": d, "list": lst, "code": "005930", "payload": {"plan": {"zones": Z, "stop": stop, "target1": 40000}}}


def test_origin_picks_latest_before_buy():
    rows = [_row("2026-10-05", "early", 34000), _row("2026-10-07", "nextday"), _row("2026-10-07", "v3"),
            _row("2026-10-08", "reversal")]                       # 매수일(10-08) 당일 것은 직전 기록이 있으면 안 씀
    o = pub._origin_of(rows, "2026-10-08")
    assert o["date"] == "2026-10-07" and o["names"] == ["V3", "유망주"] and o["stop"] == 35000
    assert [z["name"] for z in o["zones"]] == ["1차", "2차", "3차"]
    assert pub._origin_of([_row("2026-10-08", "uplimit")], "2026-10-08")["names"] == ["상파"]   # 직전이 없으면 그날
    assert pub._origin_of([_row("2026-10-09", "v3")], "2026-10-08") is None


class _SB:
    def __init__(self, rows):
        self.rows, self.updates = rows, []

    def select(self, table, params):
        assert table == "candidates"
        return self.rows

    def update(self, table, filters, patch, returning=False):
        self.updates.append((filters, patch))


def test_watch_origins_saves_once():
    sb = _SB([_row("2026-10-07", "early")])
    opens = [{"id": "p1", "code": "005930", "entry_time": "2026-10-08 09:10:00", "plan": {"verdict": "x"}, "list_key": None},
             {"id": "p2", "code": "000660", "entry_time": "2026-10-08 09:10:00", "plan": {"origin": {"names": ["V3"]}}}]
    o = pub.watch_origins(sb, opens)
    assert o["p1"]["names"] == ["상승초기"] and o["p2"]["names"] == ["V3"]
    (f, patch), = sb.updates
    assert f == {"id": "eq.p1"} and patch["plan"]["verdict"] == "x" and patch["plan"]["origin"]["stop"] == 35000
    assert patch["list_key"] == "early"
