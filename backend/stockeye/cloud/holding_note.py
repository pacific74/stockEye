"""장마감 리포트 하단 '보유종목 코멘트' — 종목마다 한 줄 (지지선·매물대·업종 흐름 기준 참고 문구)

  · 가장 가까운 지지선 이탈 / 2% 안으로 접근 → 경고
  · 위 8% 안에 저항(매물대·이평선)이 2개 이상이거나 3% 안에 가까운 저항이 있고 수익 중이면 → 일부 매도 고려
  · 소속 업종(테마) 오늘 등락 -1% 이하 → 업종 약세
지표를 정리한 참고 문장이며 매매 권유가 아닙니다. 아무 조건도 없으면 코멘트 없음 (None).
"""
from __future__ import annotations

SUP_NEAR = 0.02        # 지지선까지 이 안이면 '접근'
RES_NEAR = 0.03        # 가까운 저항
RES_ZONE = 0.08        # 이 범위 안 저항 개수
SEC_DROP = -1.0        # 업종 약세 기준 (%)


def _w(p) -> str:
    return f"{int(round(float(p))):,}"


def sector_of(report: dict, code: str) -> tuple[str, float] | None:
    """종목이 속한 업종(테마) 중 리포트 업종 순서상 첫 번째 → (이름, 오늘 등락%)"""
    mem = ((report.get("sector_members") or {}).get("groups")) or {}
    for g in report.get("sectors") or []:
        rows = mem.get(g.get("group")) or []
        if any(r and r[0] == code for r in rows) and g.get("ret1_pct") is not None:
            return g["group"], float(g["ret1_pct"])
    return None


def note_for(price: float, pnl_pct: float | None, lv: dict | None, sector: tuple[str, float] | None) -> str | None:
    bits: list[str] = []
    if lv and price:
        sups = [s["price"] for s in lv.get("supports") or [] if s.get("price")]
        if sups:
            s0 = max(sups)                                    # 현재가 아래 가장 가까운 지지
            below = [s for s in sups if s <= price]
            if below:
                s0 = max(below)
                if price / s0 - 1 <= SUP_NEAR:
                    bits.append(f"지지 {_w(s0)} 근접 · 이탈 시 경고")
            else:
                bits.append(f"지지 {_w(max(sups))} 이탈 ⚠")
        res = [r["price"] for r in lv.get("resistances") or [] if r.get("price") and r["price"] > price]
        zone = [r for r in res if r / price - 1 <= RES_ZONE]
        if res and (pnl_pct or 0) > 0 and (len(zone) >= 2 or min(res) / price - 1 <= RES_NEAR):
            bits.append(f"위 {_w(min(res))} 부근 매물대 저항 → 일부 매도 고려")
    if sector and sector[1] <= SEC_DROP:
        bits.append(f"{sector[0]} 업종 {sector[1]:+.1f}% 약세")
    return " · ".join(bits) if bits else None
