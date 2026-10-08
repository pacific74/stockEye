"""앱이 읽는 Supabase 표에 결과 발행."""
from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd

from ..engine.strategies import STRATEGIES, LIMITATIONS
from .client import Supabase

log = logging.getLogger(__name__)

STRAT_KEYS = list(STRATEGIES)


def _strategy_summary(report: dict) -> dict:
    return {k: {"name": v["name"], "short": v["short"], "description": v["description"],
                "limitation": v.get("limitation"), "count": v.get("count", len(v["candidates"])),
                "top": [{"code": c["code"], "name": c["name"], "score": c["score"],
                         "strategy_score": c.get("strategy_score"), "verdict": c["plan"]["verdict"]}
                        for c in v["candidates"][:3]]}
            for k, v in report["strategies"].items()}


def publish_report(sb: Supabase, report: dict, keep_days: int = 60) -> None:
    d = report["date"]
    sb.upsert("daily_reports", [{
        "date": d, "as_of": str(report["as_of"])[:19],
        # V2 시장 상태(A/B/C)·등급 개수는 market 안에 같이 넣음 (표 구조 변경 없이)
        "market": {**report["market"], "engine": report.get("engine", "v1"), **({"v2": report["v2"]} if report.get("v2") else {})},
        "sectors": report["sectors"],
        "top10": report["top10"], "strategies": _strategy_summary(report), "funnel": report["funnel"],
        "labels": report.get("labels"), "unmatched_theme_names": report.get("unmatched_theme_names", []),
        "ai_explained": len(report.get("explanations", {}))}], "date")
    rows = []
    for lst, cands in [("overall", report["candidates"])] + [(k, v["candidates"]) for k, v in report["strategies"].items()]:
        for c in cands:
            rows.append({"date": d, "list": lst, "rank": c["rank"], "code": c["code"], "name": c["name"],
                         "score": c["score"], "strategy_score": c.get("strategy_score"),
                         "verdict": c["plan"]["verdict"], "payload": c})
    sb.delete("candidates", {"date": f"eq.{d}"})          # 같은 날 다시 돌렸을 때 빠진 종목이 남지 않게
    sb.upsert("candidates", rows, "date,list,code")
    old = (pd.Timestamp(d) - pd.Timedelta(days=keep_days)).strftime("%Y-%m-%d")
    sb.delete("candidates", {"date": f"lt.{old}"})
    sb.delete("daily_reports", {"date": f"lt.{old}"})
    if report.get("engine") == "v2":
        meta = [{"key": "V2", "name": "매수후보 V2 엔진", "short": "V2",
                 "description": "시장 → 업종 → 재무·공시 위험 → 기술 → 100점 → 가격위치 → 과열 → 매수 신호. "
                                "분할 매수 30/30/40, 익절 +8%·+15%·20일선 이탈",
                 "limitation": "재무·공시는 DART 기준(뉴스 기사 제외). 업종 분류는 현재 기준."}]
    else:
        meta = [{"key": k, "name": s.name, "short": s.short, "description": s.description,
                 "limitation": LIMITATIONS.get(k)} for k, s in STRATEGIES.items()]
    sb.upsert("system_status", [{"key": "strategies", "payload": meta}], "key")
    log.info("리포트 발행: %s (후보 %d행, 업종 %d)", d, len(rows), len(report["sectors"]))


def publish_details(sb: Supabase, rows: list[dict], date: str, stale_days: int = 30) -> None:
    sb.upsert("stock_details", rows, "code", chunk=150)
    old = (pd.Timestamp(date) - pd.Timedelta(days=stale_days)).strftime("%Y-%m-%d")
    sb.delete("stock_details", {"date": f"lt.{old}"})         # 상장폐지 등으로 더 이상 안 나오는 종목
    log.info("종목 상세 발행: %d종목", len(rows))


def publish_backtest(sb: Supabase, key: str, name: str, result: dict) -> None:
    sb.upsert("backtests", [{"key": key, "name": name, "start_date": result.get("start"), "end_date": result.get("end"),
                             "metrics": result.get("metrics"), "metrics_oos": result.get("metrics_oos"),
                             "audit_passed": (result.get("audit") or {}).get("passed"), "payload": result,
                             "updated_at": datetime.utcnow().isoformat() + "Z"}], "key")


def publish_status(sb: Supabase, key: str, payload: dict) -> None:
    sb.upsert("system_status", [{"key": key, "payload": payload,
                                 "updated_at": datetime.utcnow().isoformat() + "Z"}], "key")


def trading_status(cfg: dict) -> dict:
    from ..trading.notify import Notifier
    tc = cfg["trading"]
    return {"mode": tc["mode"], "broker": tc.get("broker"), "allow_real_orders": tc.get("allow_real_orders", False),
            "notify_channels": Notifier().channels, "paper_capital": tc.get("paper_capital", 10_000_000),
            "updated": datetime.now().strftime("%Y-%m-%d %H:%M")}


def publish_journal(sb: Supabase, cfg: dict, journal, pit=None, report: dict | None = None) -> None:
    """매매 분석(전체·모드별) + 보유종목 점검을 미리 계산해서 올림."""
    from ..trading.analysis import analyze, ai_summary
    uid = journal.uid
    df = journal.frame()
    modes = ["all"] + (sorted(df["mode"].dropna().unique()) if not df.empty else [])
    rows = []
    for m in modes:
        stats = analyze(df if m == "all" else df[df["mode"] == m])
        rows.append({"user_id": uid, "mode": m, "payload": {"stats": stats, "summary": ai_summary(stats, cfg)},
                     "updated_at": datetime.utcnow().isoformat() + "Z"})
    sb.upsert("journal_analysis", rows, "user_id,mode")

    if pit is None or report is None:
        return
    opens = journal.positions(status="open")
    if not opens:
        return
    from ..indicators import compute_features
    from .. import portfolio as pf
    holds = [{**p, "avg_price": p["entry_price"], "target": p["target1"], "buy_date": p["entry_time"][:10]} for p in opens]
    oh = pit.ohlcv[pit.ohlcv["code"].isin([h["code"] for h in holds])]
    if oh.empty:
        return
    oh = oh[oh["date"] >= oh["date"].max() - pd.Timedelta(days=120)]
    x = compute_features(oh).xs(oh["date"].max(), level="date")
    idx = {}
    for c in report["candidates"] + [c for v in report["strategies"].values() for c in v["candidates"]]:
        idx.setdefault(c["code"], {"score": c["score"], "tags": c.get("tags", [])})
    reviews = pf.review(holds, x, report["date"], idx, cfg["backtest"]["max_hold_days"])
    keep = ("price", "pnl_pct", "pnl", "ret1_pct", "alerts", "status", "hold_days", "today_score", "today_tags")
    sb.upsert("position_reviews", [{"position_id": r["id"], "user_id": uid, "payload": {k: r.get(k) for k in keep},
                                    "updated_at": datetime.utcnow().isoformat() + "Z"} for r in reviews],
              "position_id")
    log.info("매매 분석 %d개 · 보유종목 점검 %d개 발행", len(rows), len(reviews))


def process_backtest_requests(sb: Supabase, pit, cfg: dict, limit: int = 3, bt=None, features=None) -> int:
    """앱에서 요청한 백테스트 실행 (queued → done). spec = {v2: true, start} (V2) / 예전 V1 형식"""
    reqs = sb.select("backtest_requests", {"status": "eq.queued", "order": "id.asc", "limit": str(limit)})
    if not reqs:
        return 0
    v2 = [q for q in reqs if (q["spec"] or {}).get("v2") or not ((q["spec"] or {}).get("strategy") or
                                                              (q["spec"] or {}).get("engine") or (q["spec"] or {}).get("rules"))]
    if v2:
        from ..backtest.engine_v2 import BacktesterV2
        from ..indicators import compute_features
        feat = features if features is not None else compute_features(pit.ohlcv, pit.flows, pit.fund)
        b2 = BacktesterV2(pit, cfg, feat)
        for q in v2:
            spec = q["spec"] or {}
            sb.update("backtest_requests", {"id": f"eq.{q['id']}"}, {"status": "running"})
            try:
                d = b2.run(spec.get("start"), spec.get("end")).to_dict()
                sb.update("backtest_requests", {"id": f"eq.{q['id']}"},
                          {"status": "done", "result": d, "done_at": datetime.utcnow().isoformat() + "Z"})
            except Exception as e:  # noqa: BLE001
                log.warning("백테스트 요청 %s 실패: %s", q["id"], e)
                sb.update("backtest_requests", {"id": f"eq.{q['id']}"},
                          {"status": "failed", "message": str(e)[:500], "done_at": datetime.utcnow().isoformat() + "Z"})
        reqs = [q for q in reqs if q not in v2]
        if not reqs:
            return len(v2)
    from ..backtest.engine import Backtester
    from ..backtest.strategy import RuleStrategy, ScreenerStrategy, NamedStrategy
    from ..backtest.lookahead import audit
    bt = bt or Backtester(pit, cfg)
    for q in reqs:
        spec = q["spec"] or {}
        sb.update("backtest_requests", {"id": f"eq.{q['id']}"}, {"status": "running"})
        try:
            if spec.get("strategy"):
                strat = NamedStrategy(spec["strategy"], cfg)
            elif spec.get("engine"):
                strat = ScreenerStrategy(cfg, float(spec.get("min_score") or 75))
            elif spec.get("rules"):
                strat = RuleStrategy(spec["rules"], cfg)
            else:
                raise ValueError("strategy / rules / engine 중 하나가 필요합니다")
            res = bt.run(strat, spec.get("start"), spec.get("end"))
            res.audit = audit(pit, bt.features, strat, res.trades).to_dict()
            d = res.to_dict()
            sb.update("backtest_requests", {"id": f"eq.{q['id']}"},
                      {"status": "done", "result": d, "done_at": datetime.utcnow().isoformat() + "Z"})
            if spec.get("strategy"):
                publish_backtest(sb, spec["strategy"], STRATEGIES[spec["strategy"]].name, d)
        except Exception as e:  # noqa: BLE001
            log.warning("백테스트 요청 %s 실패: %s", q["id"], e)
            sb.update("backtest_requests", {"id": f"eq.{q['id']}"},
                      {"status": "failed", "message": str(e)[:500], "done_at": datetime.utcnow().isoformat() + "Z"})
    return len(reqs)


ALERT_STATUSES = ("손절 검토", "익절 검토", "확인 필요")


def report_summary(report: dict) -> str:
    """알림 한 줄 요약: (V2) 시장 상태 · 매수 신호 수 · TOP3"""
    m = report["market"]
    top = ", ".join(f"{c['name']}({c['score']:.0f})" for c in report["top10"][:3]) or "후보 없음"
    v2 = report.get("v2")
    if v2:
        ms = " ".join(f"{'코스피' if k == 'KOSPI' else '코스닥'} {v['label']}" for k, v in v2.get("market", {}).items())
        return f"{ms} · 매수 신호 {v2.get('counts', {}).get('매수 신호', 0)}개 · TOP3 {top}"
    return f"{m.get('mood_icon', '')} {m.get('mood', '')} · TOP3 {top}"


def notify_members(sb: Supabase, report: dict, notifier, skip_topics=(), app_url: str | None = None) -> int:
    """알림 토픽을 등록한 승인 회원에게 각자 알림: 오늘 리포트 요약 + 내 보유종목 경고."""
    try:
        members = sb.select("profiles", {"select": "user_id,ntfy_topic,notify_daily,notify_holdings",
                                         "status": "eq.approved", "ntfy_topic": "not.is.null"})
    except Exception as e:  # noqa: BLE001  (예전 스키마)
        log.info("회원 알림 생략: %s", e)
        return 0
    summary = report_summary(report)
    skip = {t.strip() for t in skip_topics if t}
    sent = 0
    for u in members:
        topic = (u.get("ntfy_topic") or "").strip()
        if not topic or topic in skip:
            continue
        if u.get("notify_holdings", True):
            reviews = sb.select("position_reviews", {"select": "position_id,payload", "user_id": f"eq.{u['user_id']}"})
            names = {p["id"]: p["name"] for p in sb.select("positions", {
                "select": "id,name", "user_id": f"eq.{u['user_id']}", "status": "eq.open"})}
            lines = []
            for r in reviews:
                pl = r["payload"] or {}
                if r["position_id"] in names and pl.get("status") in ALERT_STATUSES:
                    first = (pl.get("alerts") or [""])[0]
                    lines.append(f"⚠ {names[r['position_id']]} [{pl['status']}] {first}")
            if lines:
                notifier.send_topic(topic, f"StockEye 보유종목 점검 ({report['date']})", "\n".join(lines[:10]),
                                    priority="high", url=app_url)
                sent += 1
        if u.get("notify_daily", True):
            notifier.send_topic(topic, f"StockEye {report['date']} 리포트", summary, url=app_url)
            sent += 1
    log.info("회원 알림 %d건 발송", sent)
    return sent
