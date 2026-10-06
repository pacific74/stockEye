"""StockEye API 서버 (Flutter 앱이 호출).

  uvicorn api.main:app --host 0.0.0.0 --port 8000

메인 화면
  GET  /api/dashboard                  오늘의 시장 + 돈이 몰리는 업종 + TOP10 + 전략별 요약
  GET  /api/candidates?list=overall    상승 후보 (overall) / 전략 A~E 후보
  GET  /api/sectors                    업종/테마 강도 전체
  GET  /api/sectors/{group}            업종/테마 상세 (소속 종목 점수)
종목
  GET  /api/search?q=삼성               종목 검색
  GET  /api/stocks/{code}              점수·매매계획·근거·주의·차트·공시·AI 설명
  GET  /api/stocks/{code}/explain      AI 설명 (판단 보조)
  GET  /api/stocks/{code}/similar      비슷한 과거 차트 패턴
  GET  /api/price/{code}               실시간 현재가 (KIS 키가 있을 때)
전략/백테스트
  GET  /api/strategies                 전략 A~E 설명 + 저장된 전략별 백테스트 요약
  POST /api/backtest                   {"strategy": "A"} 또는 {"rules": [...]} 또는 {"engine": true}
  GET  /api/backtest/latest
보유종목 (= 매매일지의 열린 포지션)
  GET/POST /api/portfolio, PATCH/DELETE /api/portfolio/{id}, GET /api/portfolio/review
매매 / 일지
  GET  /api/trading/status             모드·브로커·알림 채널·승인 대기 수·모의계좌 현금
  GET  /api/orders?status=pending      승인 대기 주문
  POST /api/orders/{id}/approve|reject 5단계 반자동: 승인 → 주문
  GET  /api/journal                    매매일지 (status=open|closed, mode=paper|kis_paper|real|manual)
  POST /api/journal/{id}/close         매도 기록 (수동 매매)
  GET  /api/journal/analysis           내 매매 분석 (전략·시간대·점수·손절지연 …)
  GET  /api/journal/analysis/ai        AI 코치 요약
"""
from __future__ import annotations

import json
import threading
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from stockeye.config import load_config, data_dir, deep_merge
from stockeye.data.store import DataStore
from stockeye.data.pit import PointInTimeData
from stockeye.engine.screener import default_as_of, analyze_one
from stockeye.engine.strategies import STRATEGIES, LIMITATIONS
from stockeye.backtest.engine import Backtester
from stockeye.backtest.strategy import RuleStrategy, ScreenerStrategy, NamedStrategy, RULE_LABELS
from stockeye.backtest.lookahead import audit
from stockeye.report import build_report, save_report, load_latest
from stockeye.ai.explainer import Explainer
from stockeye.analysis.similar import PatternIndex
from stockeye.indicators import compute_features
from stockeye import portfolio as pf
from stockeye.trading.journal import Journal
from stockeye.trading.engine import TradingEngine, Quote
from stockeye.trading.analysis import analyze as analyze_journal, ai_summary
from stockeye.trading.notify import Notifier

app = FastAPI(title="StockEye API", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_state: dict[str, Any] = {}
_lock = threading.Lock()


def _ctx():
    """데이터를 메모리에 캐시. 데이터 파일이 갱신되면 다시 로드."""
    cfg = load_config()
    store = DataStore(data_dir(cfg))
    p = store.path("ohlcv")
    if not p.exists():
        raise HTTPException(503, "데이터가 없습니다. 먼저 python -m scripts.collect 를 실행하세요.")
    mtime = p.stat().st_mtime
    with _lock:
        if _state.get("mtime") != mtime:
            _state.clear()
            _state.update(mtime=mtime, cfg=cfg, store=store, pit=PointInTimeData.from_store(store))
    return _state


def _report():
    st = _ctx()
    rep = load_latest(st["cfg"])
    last = str(st["pit"].trading_dates()[-1].date())
    if rep is None or rep["date"] != last:
        if "building" in st:
            raise HTTPException(503, "오늘 리포트를 만드는 중입니다. 1~2분 뒤 다시 시도하세요.")
        st["building"] = True
        try:
            rep = build_report(st["pit"], st["cfg"])
            save_report(rep, st["cfg"])
        finally:
            st.pop("building", None)
    return rep


def _names():
    pit = _ctx()["pit"]
    return pit.listing if not pit.listing.empty else pd.DataFrame(columns=["code", "name", "market"])


def _find(rep, code):
    for c in rep["candidates"]:
        if c["code"] == code:
            return c
    for v in rep["strategies"].values():
        for c in v["candidates"]:
            if c["code"] == code:
                return c
    return None


@app.get("/api/health")
def health():
    return {"ok": True}


# ---------------------------------------------------------------- 메인
@app.get("/api/dashboard")
def dashboard(sectors: int = 8):
    rep = _report()
    strat = {k: {"name": v["name"], "short": v["short"], "description": v["description"],
                 "count": len(v["candidates"]),
                 "top": [{"code": c["code"], "name": c["name"], "score": c["score"],
                          "strategy_score": c.get("strategy_score"), "verdict": c["plan"]["verdict"]}
                         for c in v["candidates"][:3]]}
             for k, v in rep["strategies"].items()}
    return {"date": rep["date"], "as_of": rep["as_of"], "market": rep["market"],
            "sectors": rep["sectors"][:sectors], "top10": rep["top10"], "strategies": strat,
            "funnel": rep["funnel"], "ai_explained": len(rep.get("explanations", {}))}


@app.get("/api/candidates")
def candidates(list: str = "overall", top: int = 30):  # noqa: A002
    rep = _report()
    if list == "overall":
        return {"list": "overall", "name": "상승 후보 (종합 점수)", "candidates": rep["candidates"][:top]}
    if list not in rep["strategies"]:
        raise HTTPException(404, f"list 는 overall 또는 {', '.join(rep['strategies'])}")
    v = rep["strategies"][list]
    return {"list": list, "name": v["name"], "description": v["description"], "limitation": v.get("limitation"),
            "candidates": v["candidates"][:top]}


@app.get("/api/sectors")
def sectors_all():
    rep = _report()
    return {"date": rep["date"], "sectors": rep["sectors"], "unmatched_theme_names": rep.get("unmatched_theme_names", [])}


@app.get("/api/sectors/{group}")
def sector_detail(group: str):
    rep = _report()
    g = next((s for s in rep["sectors"] if s["group"] == group), None)
    if g is None:
        raise HTTPException(404, "업종/테마 없음")
    return g


# ---------------------------------------------------------------- 종목
@app.get("/api/search")
def search(q: str, limit: int = 20):
    n = _names()
    m = n[n["name"].str.contains(q, case=False, na=False) | n["code"].str.startswith(q)]
    return [{"code": r.code, "name": r.name, "market": getattr(r, "market", "")} for r in m.head(limit).itertuples()]


@app.get("/api/stocks/{code}")
def get_stock(code: str, days: int = 120):
    rep = _report()
    st = _ctx()
    view = st["pit"].view(pd.Timestamp(rep["as_of"]))
    cand = _find(rep, code) or analyze_one(view, code, st["cfg"], _names())
    if cand is None:
        raise HTTPException(404, "종목 데이터 없음")
    oh = view.ohlcv(code).sort_values("date").tail(days)
    chart = [{"date": str(r.date.date()), "open": float(r.open), "high": float(r.high), "low": float(r.low),
              "close": float(r.close), "volume": float(r.volume)} for r in oh.itertuples()]
    disc = view.disclosures(code, since_days=30)
    return {"candidate": cand, "chart": chart,
            "explanation": rep.get("explanations", {}).get(code),
            "disclosures": [{"published_at": str(r.published_at), "title": r.title} for r in disc.itertuples()]
            if not disc.empty else []}


@app.get("/api/stocks/{code}/explain")
def explain(code: str):
    rep = _report()
    if code in rep.get("explanations", {}):
        return rep["explanations"][code]
    st = _ctx()
    cand = _find(rep, code) or analyze_one(st["pit"].view(pd.Timestamp(rep["as_of"])), code, st["cfg"], _names())
    if cand is None:
        raise HTTPException(404, "종목 데이터 없음")
    g = next((s for s in rep["sectors"] if s["type"] == "theme" and code in [m["code"] for m in s["top"]]), None)
    return Explainer(st["cfg"], data_dir(st["cfg"]) / "ai_cache").explain(cand, rep["date"], rep["market"], g)


@app.get("/api/stocks/{code}/similar")
def similar(code: str, window: int = 20, top: int = 10):
    st = _ctx()
    key = f"pattern:{window}"
    if key not in st:
        st[key] = PatternIndex(st["pit"].ohlcv, window=window)
    rep = _report()
    res = st[key].search(code, rep["date"], top=top)
    if "error" in res:
        raise HTTPException(404, res["error"])
    nm = dict(zip(_names()["code"], _names()["name"]))
    for m in res["matches"]:
        m["name"] = nm.get(m["code"], m["code"])
    res["name"] = nm.get(code, code)
    return res


@app.get("/api/price/{code}")
def live_price(code: str):
    st = _ctx()
    try:
        from stockeye.data.sources.kis_source import KISClient
        if "kis" not in st:
            kc = st["cfg"].get("kis", {})
            st["kis"] = KISClient(kc.get("env", "prod"), data_dir(st["cfg"]) / ".kis_token.json", kc.get("calls_per_sec", 15))
        return st["kis"].price(code)
    except RuntimeError as e:
        raise HTTPException(503, str(e))


# ---------------------------------------------------------------- 전략 / 백테스트
@app.get("/api/strategies")
def strategies():
    d = data_dir(load_config()) / "backtests"
    out = []
    for k, s in STRATEGIES.items():
        bt = None
        p = d / f"{k}.json"
        if p.exists():
            js = json.loads(p.read_text(encoding="utf-8"))
            bt = {"start": js["start"], "end": js["end"], "metrics": js["metrics"], "metrics_oos": js["metrics_oos"],
                  "audit_passed": (js.get("audit") or {}).get("passed")}
        out.append({"key": k, "name": s.name, "short": s.short, "description": s.description,
                    "limitation": LIMITATIONS.get(k), "backtest": bt})
    return out


@app.get("/api/rules")
def rules():
    return [{"key": k, "label": v} for k, v in RULE_LABELS.items()]


class BacktestReq(BaseModel):
    strategy: str | None = None      # "A"~"E"
    rules: list[Any] | None = None   # 예: ["close_gt_sma20", {"vol_ratio_gte": 2}]
    engine: bool = False             # True = 종합 점수 엔진 그대로
    min_score: float = 75
    start: str | None = None
    end: str | None = None
    run_audit: bool = True


@app.post("/api/backtest")
def run_backtest(req: BacktestReq):
    st = _ctx()
    cfg = st["cfg"]
    if "bt" not in st:
        st["bt"] = Backtester(st["pit"], cfg)   # 피처 계산(가장 오래 걸림)은 한 번만
    bt: Backtester = st["bt"]
    try:
        if req.strategy:
            strat = NamedStrategy(req.strategy, cfg)
        elif req.engine:
            strat = ScreenerStrategy(cfg, req.min_score)
        elif req.rules:
            strat = RuleStrategy(req.rules, cfg)
        else:
            raise HTTPException(400, "strategy / rules / engine 중 하나를 지정하세요")
    except KeyError as e:
        raise HTTPException(400, str(e))
    res = bt.run(strat, req.start, req.end)
    if req.run_audit:
        res.audit = audit(st["pit"], bt.features, strat, res.trades).to_dict()
    d = res.to_dict()
    out = data_dir(cfg)
    (out / "backtest_latest.json").write_text(json.dumps(d, ensure_ascii=False, default=str), encoding="utf-8")
    if req.strategy:
        (out / "backtests").mkdir(exist_ok=True)
        (out / "backtests" / f"{req.strategy}.json").write_text(json.dumps(d, ensure_ascii=False, default=str), encoding="utf-8")
    return d


@app.get("/api/backtest/latest")
def latest_backtest(strategy: str | None = None):
    d = data_dir(load_config())
    p = d / "backtests" / f"{strategy}.json" if strategy else d / "backtest_latest.json"
    if not p.exists():
        raise HTTPException(404, "아직 백테스트 결과가 없습니다")
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 매매일지 / 보유종목
def _journal() -> Journal:
    return Journal(data_dir(load_config()) / "journal.db")


class Holding(BaseModel):
    code: str
    name: str | None = None
    qty: float = 0
    avg_price: float
    buy_date: str | None = None        # "YYYY-MM-DD" 또는 "YYYY-MM-DD HH:MM"
    stop: float | None = None
    target: float | None = None
    target2: float | None = None
    strategy: str | None = None
    memo: str | None = None


@app.get("/api/portfolio")
def portfolio_list():
    return _journal().positions(status="open")


@app.post("/api/portfolio")
def portfolio_add(h: Holding):
    """직접 산 종목 기록 → 매매일지(manual)에 '그날 분석 스냅샷'과 함께 저장."""
    rep = load_latest(load_config()) or {}
    cand = _find(rep, h.code) if rep else None
    nm = dict(zip(_names()["code"], _names()["name"]))
    t = h.buy_date or pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
    entry_time = t if len(t) > 10 else t + " 09:00"
    pid = _journal().open_position(
        "manual", h.code, h.avg_price, h.qty, name=h.name or nm.get(h.code, h.code), cand=cand,
        entry_time=entry_time + (":00" if len(entry_time) == 16 else ""), market_mood=rep.get("market", {}).get("mood"),
        list_key=(cand or {}).get("strategy") or ("overall" if cand else None),
        stop=h.stop, target1=h.target, target2=h.target2, memo=h.memo)
    return _journal().get_position(pid)


@app.patch("/api/portfolio/{pid}")
def portfolio_update(pid: str, patch: dict):
    r = _journal().update_position(pid, patch)
    if r is None:
        raise HTTPException(404, "없음")
    return r


@app.delete("/api/portfolio/{pid}")
def portfolio_delete(pid: str):
    return {"deleted": _journal().delete_position(pid)}


@app.get("/api/portfolio/review")
def portfolio_review():
    st = _ctx()
    rep = _report()
    opens = _journal().positions(status="open")
    if not opens:
        return []
    holds = [{**p, "avg_price": p["entry_price"], "target": p["target1"], "buy_date": p["entry_time"][:10]} for p in opens]
    view = st["pit"].view(pd.Timestamp(rep["as_of"]))
    oh = view.ohlcv([h["code"] for h in holds])
    oh = oh[oh["date"] >= oh["date"].max() - pd.Timedelta(days=60)]
    x = compute_features(oh).xs(oh["date"].max(), level="date")
    idx = {c["code"]: {"score": c["score"], "tags": c.get("tags", [])} for c in rep["candidates"]}
    for v in rep["strategies"].values():
        for c in v["candidates"]:
            idx.setdefault(c["code"], {"score": c["score"], "tags": c.get("tags", [])})
    return pf.review(holds, x, rep["date"], idx, st["cfg"]["backtest"]["max_hold_days"])


class CloseReq(BaseModel):
    price: float
    reason: str = "수동"
    exit_time: str | None = None


@app.post("/api/journal/{pid}/close")
def journal_close(pid: str, req: CloseReq):
    try:
        return _journal().close_position(pid, req.price, reason=req.reason,
                                         exit_time=req.exit_time and (req.exit_time + (":00" if len(req.exit_time) == 16 else "")))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/journal")
def journal_list(status: str | None = None, mode: str | None = None, limit: int = 200):
    return _journal().positions(status=status, mode=mode)[:limit]


@app.get("/api/journal/analysis")
def journal_analysis(mode: str | None = None, min_n: int = 20):
    return analyze_journal(_journal().frame(mode=mode), min_n=min_n)


@app.get("/api/journal/analysis/ai")
def journal_analysis_ai(mode: str | None = None, min_n: int = 20):
    cfg = load_config()
    stats = analyze_journal(_journal().frame(mode=mode), min_n=min_n)
    return {"stats": stats, "summary": ai_summary(stats, cfg)}


# ---------------------------------------------------------------- 실시간 매매 (승인)
@app.get("/api/trading/status")
def trading_status():
    cfg = load_config()
    tc = cfg["trading"]
    j = _journal()
    return {"mode": tc["mode"], "broker": tc.get("broker"), "allow_real_orders": tc.get("allow_real_orders", False),
            "notify_channels": Notifier().channels, "pending_orders": len(j.orders(status="pending")),
            "open_positions": len(j.positions(status="open")),
            "paper_cash": j.cash("paper", tc.get("paper_capital", 10_000_000)),
            "recent_alerts": j.alerts(10)}


@app.get("/api/orders")
def orders(status: str | None = "pending"):
    j = _journal()
    j.expire_orders()
    return j.orders(status=status)


def _engine():
    cfg = load_config()
    from stockeye.trading.brokers import make_broker
    return TradingEngine(cfg, _journal(), load_latest(cfg), Notifier(), make_broker(cfg)), cfg


def _quote(code: str, fallback: float | None) -> Quote:
    try:
        p = live_price(code)
        return Quote(code, p["price"], p.get("open"), p.get("high"), p.get("low"), p.get("prev_close"))
    except HTTPException:
        if fallback is None:
            raise HTTPException(503, "현재가를 가져올 수 없습니다 (KIS 키 필요)")
        return Quote(code, float(fallback))     # KIS 없으면 신호 당시 가격으로 (내부 모의용)


@app.post("/api/orders/{oid}/approve")
def order_approve(oid: str):
    eng, cfg = _engine()
    o = eng.j.get_order(oid)
    if not o:
        raise HTTPException(404, "주문 없음")
    return eng.approve(oid, _quote(o["code"], o["price"]))


@app.post("/api/orders/{oid}/reject")
def order_reject(oid: str):
    eng, _ = _engine()
    return eng.reject(oid)



# ---------------------------------------------------------------- 웹앱 (휴대폰 브라우저용)
# app 폴더에서  flutter build web --base-href /app/  하면 이 서버가 http://PC주소:8000/app/ 로 앱 화면을 내보낸다.
from pathlib import Path as _Path  # noqa: E402

from fastapi.responses import RedirectResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

_WEB = _Path(__file__).resolve().parents[2] / "app" / "build" / "web"
if _WEB.exists():
    app.mount("/app", StaticFiles(directory=_WEB, html=True), name="webapp")

    @app.get("/", include_in_schema=False)
    def _root():
        return RedirectResponse("/app/")
