"""AI 설명 엔진 — '판단 보조' 전용.

역할 분리:
  통계/알고리즘 = 실제 신호 (점수, 매수구간, 목표가, 손절가, 판정)
  AI           = 그 결과를 사람이 이해할 수 있는 문장으로 설명

AI 가 하지 않는 것:
  - 점수/가격/판정을 새로 만들거나 바꾸지 않는다
  - 입력에 없는 정보(뉴스, 실적 전망 등)를 지어내지 않는다
  - "사라/팔아라" 같은 지시를 하지 않는다

안전장치:
  - AI 에게는 그날 PIT 뷰에서 계산된 숫자만 전달 (미래 데이터가 들어갈 수 없음)
  - 답변 속 숫자가 입력에 없는 값이면 → 버리고 규칙 기반 문장으로 대체
  - ANTHROPIC_API_KEY 가 없으면 규칙 기반 문장만 사용
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from pathlib import Path

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """너는 한국 주식 분석 결과를 개인 투자자에게 쉽게 설명하는 보조자다.
규칙:
1. 아래 JSON 으로 주어진 분석 결과만 근거로 쓴다. JSON 에 없는 사실(뉴스, 업황, 실적 전망, 목표주가 등)을 만들지 않는다.
2. 점수·가격·비율은 JSON 에 있는 숫자 그대로만 쓴다. 새로운 숫자를 계산하거나 반올림을 바꾸지 않는다.
3. 판정(verdict)을 바꾸지 않는다. "매수하세요/매도하세요" 같은 지시 대신 "~가 유리해 보인다", "~를 확인할 필요가 있다" 처럼 쓴다.
4. 한국어, 3~5문장, 존댓말 없이 간결한 분석 문체. 장점 → 위험 → 대응 순서.
5. 마지막 문장은 주의사항(warnings)이 있으면 그것을 반영한다."""

NUM_RE = re.compile(r"[-+]?\d[\d,]*\.?\d*")


def _numbers(obj) -> set[str]:
    s = json.dumps(obj, ensure_ascii=False)
    out = set()
    for m in NUM_RE.findall(s):
        n = m.replace(",", "").lstrip("+")
        out.add(n)
        try:
            f = float(n)
            out.update({str(int(f)) if f == int(f) else n, f"{f:.1f}", f"{f:.0f}", f"{f:.2f}"})
            out.add(str(abs(int(f))) if f == int(f) else str(abs(f)))
        except ValueError:
            pass
    return out


def _payload(c: dict, market: dict | None = None, sector: dict | None = None) -> dict:
    p = c["plan"]
    labels = {"trend": "추세", "volume": "거래량", "trading_value": "거래대금", "supply": "수급",
              "breakout": "돌파/가격위치", "volatility": "변동성", "financial": "재무", "news": "뉴스/공시"}
    part_pct = {labels[k]: round(v / c["max_parts"][k] * 100) for k, v in c["parts"].items() if c["max_parts"].get(k)}
    d = {
        "종목": c["name"], "종합점수": c["score"], "항목별_달성률(%)": part_pct,
        "판정": p["verdict"], "판정사유": p["verdict_reason"],
        "현재가": p["price"], "매수구간": [p["entry_low"], p["entry_high"]],
        "1차목표": p["target1"], "1차목표수익률(%)": p["target1_pct"],
        "손절가": p["stop"], "예상손실(%)": p["loss_pct"], "손익비": p["rr1"],
        "매수근거": c["reasons"], "주의사항": c["warnings"],
    }
    if c.get("strategy"):
        d["전략"] = c["strategy"]
        d["전략점수"] = c.get("strategy_score")
        d["전략근거"] = c.get("strategy_reasons", [])
    if market:
        d["시장분위기"] = market.get("mood")
    if sector:
        d["소속테마"] = {"이름": sector["group"], "강도점수": sector["score"]}
    return d


def rule_based(c: dict) -> str:
    """API 키가 없거나 AI 답변이 검증에 실패했을 때 쓰는 규칙 기반 설명."""
    p, r, w = c["plan"], c["reasons"], c["warnings"]
    pos = []
    if any("이동평균선 상승" in x or "정배열" in x for x in r):
        pos.append("상승 추세에 있고")
    vol = next((x for x in r if x.startswith("거래량")), None)
    if vol:
        pos.append(f"{vol.replace('증가', '').strip()} 수준으로 거래가 늘었으며")
    sup = [x for x in r if "외국인" in x or "기관" in x]
    if sup:
        pos.append(f"{sup[0]}가 이어지고 있다")
    brk = any("고점 돌파" in x for x in r)
    s1 = ("현재 " + " ".join(pos)) if pos else f"종합점수 {c['score']}점으로 일부 조건을 충족한다"
    if not s1.endswith("다"):
        s1 = s1.rstrip("고며 ") + "다"
    s2 = "최근 고점을 넘어서며 가격 위치도 좋다." if brk else ""
    risk = ""
    if w:
        risk = f"다만 {', '.join(x.split(' (')[0] for x in w[:2])} 신호가 있어 "
    v = p["verdict"]
    if c.get("engine") == "v2":
        ms = {"A": "상승장", "B": "중립", "C": "하락장"}.get(c.get("market_state"), "")
        head = f"시장 {ms}, " if ms else ""
        if v == "매수 신호":
            act = (f"{head}지지선 반등이 확인돼 매수 신호다. 매수구간 {p['entry_low']:,}~{p['entry_high']:,}원, "
                   f"손절 {p['stop']:,}원 기준으로 1차 30%만 사고, 반등이 이어지면 30%, 고점을 넘으면 40%를 더하는 분할 매수가 좋다.")
        elif v in ("강력 후보", "매수 후보"):
            act = f"{head}{v}지만 아직 매수 자리는 아니다. 20일선이나 지지선 부근에서 양봉 반등과 거래량을 확인한 뒤 진입하는 편이 낫다."
        elif v == "매수 차단":
            act = f"점수와 관계없이 매수를 피해야 한다 ({', '.join(c.get('blocks') or [])})."
        else:
            act = f"{head}{p.get('verdict_reason', '현재는 관망이 적절해 보인다')}."
        return " ".join(x for x in [s1 + ".", s2, risk + act] if x).replace("..", ".")
    if v == "눌림 대기":
        act = f"추격매수보다는 {p['entry_low']:,}원 부근 눌림목 진입이 유리해 보인다."
    elif p["verdict"] == "매수 고려":
        act = (f"매수구간은 {p['entry_low']:,}~{p['entry_high']:,}원, 손절 {p['stop']:,}원 기준으로 "
               f"손익비 1:{p['rr1']} 이다.")
    elif p["verdict"] == "관심":
        act = "조건이 일부만 충족돼 추가 확인이 필요하다."
    else:
        act = "현재는 관망이 적절해 보인다."
    return " ".join(x for x in [s1 + ".", s2, risk + act] if x).replace("..", ".")


class Explainer:
    def __init__(self, cfg: dict, cache_dir: str | Path | None = None):
        ai = cfg.get("ai", {})
        self.model = ai.get("model", "claude-sonnet-5-5")
        self.max_tokens = ai.get("max_tokens", 600)
        self.enabled = ai.get("enabled", True) and bool(os.getenv("ANTHROPIC_API_KEY"))
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._client = None

    def _client_(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()
        return self._client

    def explain(self, c: dict, date: str, market: dict | None = None, sector: dict | None = None) -> dict:
        payload = _payload(c, market, sector)
        key = hashlib.sha1(json.dumps([date, payload], ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
        if self.cache_dir and (self.cache_dir / f"{key}.json").exists():
            return json.loads((self.cache_dir / f"{key}.json").read_text(encoding="utf-8"))

        out = {"text": rule_based(c), "source": "rule", "model": None, "verified": True}
        if self.enabled:
            try:
                msg = self._client_().messages.create(
                    model=self.model, max_tokens=self.max_tokens, system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content":
                               "다음 분석 결과를 설명해줘.\n```json\n" + json.dumps(payload, ensure_ascii=False, indent=1) + "\n```"}],
                )
                text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
                ok, bad = verify_numbers(text, payload)
                if ok and text:
                    out = {"text": text, "source": "ai", "model": self.model, "verified": True}
                else:
                    log.warning("AI 설명에 입력에 없는 숫자 %s → 규칙 기반 문장 사용", bad)
                    out["note"] = f"AI 답변에 근거 없는 숫자({', '.join(bad[:3])})가 있어 규칙 기반 설명으로 대체"
            except Exception as e:  # noqa: BLE001
                log.warning("AI 설명 실패: %s", e)
                out["note"] = "AI 호출 실패 → 규칙 기반 설명"
        out["disclaimer"] = "AI 설명은 위 점수·신호를 풀어 쓴 참고용이며, 매매 신호는 통계/알고리즘 결과입니다."
        if self.cache_dir:
            (self.cache_dir / f"{key}.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        return out


def verify_numbers(text: str, payload: dict) -> tuple[bool, list[str]]:
    """설명문 속 숫자가 모두 입력(payload)에 있던 숫자인지 확인. (1~3 같은 작은 정수, 연도 등은 허용)"""
    allowed = _numbers(payload)
    bad = []
    for m in NUM_RE.findall(text):
        n = m.replace(",", "").lstrip("+").rstrip(".")
        if not n or n in allowed:
            continue
        try:
            f = float(n)
        except ValueError:
            continue
        if f.is_integer() and 0 <= f <= 10:      # "1차", "2가지" 같은 서수/개수
            continue
        if str(abs(f)) in allowed or f"{abs(f):.1f}" in allowed or str(int(abs(f))) in allowed:
            continue
        bad.append(m)
    return (not bad), bad
