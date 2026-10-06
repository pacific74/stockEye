"""내 매매 분석 — "내 매매 500건을 분석해줘".

통계(이 파일)가 숫자를 계산하고, AI 는 그 숫자만 받아 '무엇이 잘 맞고 무엇이 안 맞는지' 문장으로 요약한다.
표본이 적은 칸(기본 20건 미만)은 '신뢰 낮음'으로 표시 — 10번 중 7번 이긴 건 우연일 수 있다.

나누는 기준:
  전략 · 진입 시간대 · 요일 · 진입 당시 점수 · 시장 분위기 · 판정 · 테마 · 보유기간 · 매도 사유
특수 진단:
  손절 지연 (손절가보다 1% 넘게 아래서 판 매매) · 너무 이른 익절 (보유 중 목표가 찍었는데 그보다 낮게 판 매매)
  승인 지연 (신호 → 체결까지 걸린 시간과 성과)
"""
from __future__ import annotations

import json
import logging
import os

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

STRAT_NAMES = {"A": "돌파매매", "B": "눌림목", "C": "급등추격", "D": "수급매매", "E": "저평가 전환", "overall": "종합 후보"}
TIME_BUCKETS = [("09:00~09:30", "09:00", "09:30"), ("09:30~11:00", "09:30", "11:00"),
                ("11:00~14:00", "11:00", "14:00"), ("14:00 이후", "14:00", "23:59")]


def _bucket_time(t: str) -> str:
    hm = str(t)[11:16]
    for name, a, b in TIME_BUCKETS:
        if a <= hm < b:
            return name
    return "장외"


def _group(df: pd.DataFrame, col: str, min_n: int, order=None) -> list[dict]:
    rows = []
    for k, g in df.groupby(col, dropna=True):
        if k in (None, "", "nan"):
            continue
        r = g["ret_pct"]
        rows.append({"group": str(k), "n": int(len(g)), "win_rate": round(float((r > 0).mean()) * 100, 1),
                     "avg_ret": round(float(r.mean()), 2), "median_ret": round(float(r.median()), 2),
                     "sum_pnl": int(g["pnl"].fillna(0).sum()), "low_confidence": len(g) < min_n})
    if order:
        rows.sort(key=lambda x: order.index(x["group"]) if x["group"] in order else 99)
    else:
        rows.sort(key=lambda x: -x["n"])
    return rows


def analyze(df: pd.DataFrame, min_n: int = 20) -> dict:
    """df = Journal.frame() (닫힌 매매만 사용)."""
    if df.empty or "status" not in df:
        return {"closed": 0, "message": "아직 완료된 매매가 없습니다"}
    d = df[df["status"] == "closed"].copy()
    if d.empty:
        return {"closed": 0, "open": int((df["status"] == "open").sum()), "message": "아직 완료된 매매가 없습니다"}
    d["ret_pct"] = d["ret_pct"].astype(float)
    d["strategy_name"] = d["strategy"].map(STRAT_NAMES).fillna(d["list_key"].map(STRAT_NAMES)).fillna("기타")
    d["time_bucket"] = d["entry_time"].map(_bucket_time)
    d["weekday"] = pd.to_datetime(d["entry_time"]).dt.dayofweek.map(dict(enumerate("월화수목금토일")))
    d["score_bucket"] = pd.cut(d["score"].astype(float), [0, 60, 70, 80, 90, 101], right=False,
                               labels=["60 미만", "60~70", "70~80", "80~90", "90 이상"]).astype(str)
    d["hold_bucket"] = pd.cut(d["hold_days"].astype(float), [-1, 1, 3, 7, 15, 10_000],
                              labels=["당일~1일", "2~3일", "4~7일", "8~15일", "16일 이상"]).astype(str)

    r = d["ret_pct"]
    wins, losses = r[r > 0], r[r <= 0]
    out = {
        "closed": int(len(d)), "open": int((df["status"] == "open").sum()),
        "period": f"{str(d['entry_time'].min())[:10]} ~ {str(d['exit_time'].max())[:10]}",
        "modes": d["mode"].value_counts().to_dict(),
        "summary": {
            "win_rate": round(float((r > 0).mean()) * 100, 1),
            "avg_ret": round(float(r.mean()), 2),
            "avg_win": round(float(wins.mean()), 2) if len(wins) else None,
            "avg_loss": round(float(losses.mean()), 2) if len(losses) else None,
            "payoff": round(float(wins.mean() / -losses.mean()), 2) if len(wins) and len(losses) and losses.mean() < 0 else None,
            "profit_factor": round(float(wins.sum() / -losses.sum()), 2) if len(losses) and losses.sum() < 0 else None,
            "total_pnl": int(d["pnl"].fillna(0).sum()),
            "avg_hold_days": round(float(d["hold_days"].mean()), 1),
            "max_consec_losses": _max_consec(list(r <= 0)),
        },
        "by_strategy": _group(d, "strategy_name", min_n),
        "by_time": _group(d, "time_bucket", min_n, [b[0] for b in TIME_BUCKETS]),
        "by_weekday": _group(d, "weekday", min_n, list("월화수목금")),
        "by_score": _group(d, "score_bucket", min_n, ["60 미만", "60~70", "70~80", "80~90", "90 이상"]),
        "by_mood": _group(d, "market_mood", min_n, ["강세", "중립", "약세"]),
        "by_verdict": _group(d, "verdict", min_n),
        "by_theme": [g for g in _group(d, "theme", min_n) if g["n"] >= 3][:10],
        "by_hold": _group(d, "hold_bucket", min_n, ["당일~1일", "2~3일", "4~7일", "8~15일", "16일 이상"]),
        "by_exit_reason": _group(d, "exit_reason", min_n),
        "min_n": min_n,
    }

    # ---- 특수 진단 ----
    diag = {}
    late = d[d["late_stop"] == 1]
    if len(late):
        on_time = d[(d["exit_reason"] == "손절") & (d["late_stop"] == 0)]
        diag["late_stop"] = {"n": int(len(late)), "avg_ret": round(float(late["ret_pct"].mean()), 2),
                             "on_time_avg_ret": round(float(on_time["ret_pct"].mean()), 2) if len(on_time) else None,
                             "extra_loss": round(float(late["ret_pct"].mean() - on_time["ret_pct"].mean()), 2) if len(on_time) else None}
    if "target1" in d and "max_price" in d:
        early = d[(d["max_price"] >= d["target1"]) & (d["exit_price"] < d["target1"] * 0.98)]
        if len(early):
            diag["missed_target"] = {"n": int(len(early)), "avg_ret": round(float(early["ret_pct"].mean()), 2),
                                     "avg_mfe": round(float(((early["max_price"] / early["entry_price"]) - 1).mean() * 100), 2)}
    if "stop" in d:
        no_stop = d[d["stop"].isna()]
        if len(no_stop):
            diag["no_stop"] = {"n": int(len(no_stop)), "avg_ret": round(float(no_stop["ret_pct"].mean()), 2)}
    if "signal_time" in d and d["signal_time"].notna().any():
        dl = d[d["signal_time"].notna()].copy()
        dl["delay_min"] = (pd.to_datetime(dl["entry_time"]) - pd.to_datetime(dl["signal_time"])).dt.total_seconds() / 60
        if len(dl) >= 5:
            fast, slow = dl[dl["delay_min"] <= 3], dl[dl["delay_min"] > 3]
            diag["approval_delay"] = {"median_min": round(float(dl["delay_min"].median()), 1),
                                      "fast_win_rate": round(float((fast["ret_pct"] > 0).mean()) * 100, 1) if len(fast) else None,
                                      "slow_win_rate": round(float((slow["ret_pct"] > 0).mean()) * 100, 1) if len(slow) else None}
    out["diagnostics"] = diag
    out["insights"] = _insights(out)
    return out


def _max_consec(flags):
    best = cur = 0
    for f in flags:
        cur = cur + 1 if f else 0
        best = max(best, cur)
    return best


def _insights(a: dict) -> list[str]:
    """규칙으로 뽑는 핵심 발견 (AI 없이도 보이는 것)."""
    out, base = [], a["summary"]["win_rate"]
    for key, label in (("by_strategy", "전략"), ("by_time", "진입 시간대"), ("by_score", "진입 점수"),
                       ("by_mood", "시장 분위기")):
        groups = [g for g in a[key] if not g["low_confidence"]]
        if len(groups) < 2:
            continue
        best = max(groups, key=lambda g: g["avg_ret"])
        worst = min(groups, key=lambda g: g["avg_ret"])
        if best["avg_ret"] - worst["avg_ret"] >= 1.0:
            out.append(f"{label}: '{best['group']}' 평균 {best['avg_ret']:+.2f}% (승률 {best['win_rate']}%, {best['n']}건) vs "
                       f"'{worst['group']}' 평균 {worst['avg_ret']:+.2f}% (승률 {worst['win_rate']}%, {worst['n']}건)")
    dg = a["diagnostics"]
    if "late_stop" in dg and dg["late_stop"].get("extra_loss") is not None:
        out.append(f"손절을 늦게 한 매매 {dg['late_stop']['n']}건: 평균 {dg['late_stop']['avg_ret']:+.2f}% "
                   f"(제때 손절 평균 {dg['late_stop']['on_time_avg_ret']:+.2f}%)")
    if "missed_target" in dg:
        out.append(f"목표가를 찍고도 그 아래에서 판 매매 {dg['missed_target']['n']}건: 평균 {dg['missed_target']['avg_ret']:+.2f}% "
                   f"(보유 중 최고 {dg['missed_target']['avg_mfe']:+.2f}%)")
    if a["closed"] < a["min_n"]:
        out.append(f"완료된 매매가 {a['closed']}건뿐이라 아직 결론을 내기 이릅니다 (최소 {a['min_n']}건 이상 권장)")
    return out


AI_SYSTEM = """너는 개인 투자자의 매매일지 통계를 읽고 개선점을 짚어주는 코치다.
규칙:
1. 주어진 JSON 통계만 근거로 쓴다. 통계에 없는 숫자를 만들거나 계산하지 않는다.
2. low_confidence=true 인 그룹은 '표본이 적어 참고만'이라고 명시한다.
3. 구성: (1) 한 줄 총평 (2) 잘 맞는 것 2~3개 (3) 안 맞는 것/고칠 습관 2~3개 (4) 다음 50건 동안 시험해볼 규칙 2개.
4. 한국어, 존댓말 없이 간결하게. 특정 종목 매수/매도 권유는 하지 않는다."""


def ai_summary(stats: dict, cfg: dict) -> dict:
    from ..ai.explainer import verify_numbers
    if stats.get("closed", 0) == 0:
        return {"text": "완료된 매매가 없어 분석할 수 없습니다.", "source": "rule"}
    rule = "\n".join(f"• {s}" for s in stats["insights"]) or "뚜렷한 차이가 아직 보이지 않습니다."
    if not (cfg.get("ai", {}).get("enabled", True) and os.getenv("ANTHROPIC_API_KEY")):
        return {"text": rule, "source": "rule"}
    payload = {k: v for k, v in stats.items() if k != "insights"}
    try:
        import anthropic
        msg = anthropic.Anthropic().messages.create(
            model=cfg.get("ai", {}).get("model", "claude-sonnet-5-5"), max_tokens=1200, system=AI_SYSTEM,
            messages=[{"role": "user", "content": "내 매매 통계를 분석해줘.\n```json\n"
                       + json.dumps(payload, ensure_ascii=False, indent=1, default=str) + "\n```"}])
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
        ok, bad = verify_numbers(text, payload)
        if ok and text:
            return {"text": text, "source": "ai", "model": cfg.get("ai", {}).get("model")}
        log.warning("AI 분석에 근거 없는 숫자 %s → 규칙 요약 사용", bad[:5])
        return {"text": rule, "source": "rule", "note": "AI 답변에 통계에 없는 숫자가 있어 규칙 요약으로 대체"}
    except Exception as e:  # noqa: BLE001
        log.warning("AI 분석 실패: %s", e)
        return {"text": rule, "source": "rule", "note": "AI 호출 실패"}
