from stockeye.analysis import shortlist as sl
from stockeye.analysis import us_tone
from stockeye.data.sources import us_futures


def test_parse_chart_meta():
    body = {"chart": {"result": [{"meta": {"regularMarketPrice": 20100.0, "chartPreviousClose": 20000.0}}]}}
    assert us_futures.parse(body) == 0.5
    assert us_futures.parse({"chart": {"result": None}}) is None
    assert us_futures.parse({}) is None


def test_tone_thresholds():
    assert us_tone.tone_of(None)["tone"] is None
    assert us_tone.tone_of({"NQ": 0.8, "ES": 0.4})["tone"] == "상승"
    assert us_tone.tone_of({"NQ": -0.9, "ES": -0.3})["tone"] == "하락"
    assert us_tone.tone_of({"NQ": 0.2, "ES": -0.1})["tone"] == "중립"
    assert us_tone.tone_of({"NQ": -0.8})["avg"] == -0.8                              # 하나만 받아도 사용
    assert "적극" in us_tone.label(us_tone.tone_of({"NQ": 1.0, "ES": 0.6}))
    assert us_tone.label({"tone": None}) == ""


def _r(code, score, status="진입 조건 충족", typ="눌림목"):
    return {"code": code, "name": code, "score": score, "status": status, "type": typ, "excluded": [], "warnings": []}


def test_shortlist_gate_with_tone():
    st = sl.new_state()
    sl.freeze(st, [_r(f"c{i}", 99 - i, "관찰") for i in range(10)] + [_r("x", 70, "관찰")], "09:10")
    r = _r("c7", 92)                                                                  # 후보 8위
    sl.gate(r, st, None)
    assert r["status"] == "진입 조건 충족"
    r = _r("c7", 92)
    sl.gate(r, st, "하락")                                                            # 보수: 상위 5개만
    assert r["status"] == "진입 대기" and "미국 선물" in r["warnings"][0]
    r = _r("c1", 92)
    sl.gate(r, st, "하락")
    assert r["status"] == "진입 조건 충족"
    r = _r("x", 87)                                                                   # 후보 밖 87점
    sl.gate(r, st, None)
    assert r["status"] == "진입 대기"
    r = _r("x", 87)
    sl.gate(r, st, "상승")                                                            # 적극: 85점부터 추가
    assert r["status"] == "진입 조건 충족" and "x" in st["late"]
