"""지수·업종 급락 경고 — '매수 주의' 표시 (메인 금일 관심주 · 관심 탭 · 저녁 리포트)

  종합지수 급락: 코스피/코스닥 그날 등락률 ≤ −3%  → 그 시장 종목 모두에 '종합지수 급락 · 매수 주의'
  업종 급락    : 종목이 속한 업종/테마(리포트 sectors 의 거래대금 가중 등락률) ≤ −3% → '업종 급락 · 매수 주의'
  ※ 업종 등락률은 KRX 업종지수가 아니라 소속 종목들의 거래대금 가중 평균 (앱의 '돈이 몰리는 업종'과 같은 값)
"""
from __future__ import annotations

DROP = -3.0
IDX_NAME = {"KOSPI": "코스피", "KOSDAQ": "코스닥"}


def annotate(report: dict, drop: float = DROP) -> dict:
    """report['market']['drop_alert'] 와 후보마다 c['market_alert'] (없으면 키 삭제). 요약 dict 반환"""
    m = report.setdefault("market", {})
    idx = {i["code"]: i.get("change_pct") for i in m.get("indices", []) if i.get("change_pct") is not None}
    grp = {g["group"]: g.get("ret1_pct") for g in report.get("sectors") or [] if g.get("ret1_pct") is not None}
    bad_idx = {k: v for k, v in idx.items() if v <= drop}
    bad_grp = {k: v for k, v in grp.items() if v <= drop}
    summary = {"threshold": drop,
               "index": [{"code": k, "name": IDX_NAME.get(k, k), "change_pct": v} for k, v in bad_idx.items()],
               "groups": [{"group": k, "ret1_pct": v} for k, v in sorted(bad_grp.items(), key=lambda kv: kv[1])][:8]}
    m["drop_alert"] = summary if (summary["index"] or summary["groups"]) else None
    for v in (report.get("strategies") or {}).values():
        for c in (v or {}).get("candidates") or []:
            msg = alert_for(c, bad_idx, bad_grp)
            if msg:
                c["market_alert"] = msg
            else:
                c.pop("market_alert", None)
    return summary


def alert_for(c: dict, bad_idx: dict, bad_grp: dict) -> str | None:
    bits = []
    mk = c.get("market")
    if mk in bad_idx:
        bits.append(f"종합지수 급락 ({IDX_NAME.get(mk, mk)} {bad_idx[mk]:+.1f}%)")
    for key in ("sector", "theme"):
        g = c.get(key)
        if g and g in bad_grp:
            bits.append(f"업종 급락 ({g} {bad_grp[g]:+.1f}%)")
            break
    return " · ".join(bits) + " · 매수 주의" if bits else None
