"""주간 조건 최적화 (제안만) — PC 에서 주 1회 (scripts_win/29_weekly_optimize.bat, 토요일)

  보관된 1분봉(data/minute_cache) 으로 당일단타 조건을 '한 번에 하나씩' 바꿔 다시 계산 → 지금 조건보다 나은 변경 1개를 '제안'
  ⚠ 자동으로 엔진에 반영하지 않음. 제안을 보고 사용자가 승인하면 scripts/apply_params.py (30_apply_params.bat) 가 반영
  과최적화 방지: 날짜순으로 앞 70% 로 고르고 뒤 30% 로 확인 (둘 다 좋아져야 제안) · 거래 수가 너무 줄면 제외 · 변경 폭은 인접 후보만
  호가·뉴스·지수 없이 중립으로 계산 (스프레드 기준은 검증 불가)
  python -m scripts.weekly_optimize --days 40
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time

import pandas as pd

log = logging.getLogger("stockeye.weekly")
TRAIN_FRAC = 0.7
MIN_TRADES, MIN_KEEP, MIN_GAIN = 30, 0.6, 0.15      # 최소 거래 수 · 기준 대비 거래 수 유지 비율 · 평균 손익 최소 개선(%p)


def work(a: dict) -> dict:
    """샘플 하나(종목·하루): 지금 조건으로 한 번 계산(점수 기준 후보별 진입도 같이) — 별도 프로세스에서도 돌게 맨 위 함수"""
    from stockeye.analysis import daytrade_eval as de
    from stockeye.engine import daytrade as dt, params as pm
    try:
        bars = pd.read_parquet(a["path"])
    except Exception:  # noqa: BLE001
        return {}
    ident = {"date": a["date"], "code": a["code"], "name": a["code"]}
    out = {}
    with pm.Overrides(dt, a["params"]):
        scan = de.scan_day(bars, a["prev_close"], adr=a["adr"], extra={"hi_n": a["hi"], "rebound": a["reb"]})
        for s in a["scores"]:
            e = de.first_entry(scan, "09:05", min_score=s)
            g = de.grade({**e, **ident}, bars) if e else None
            out[str(s)] = {"date": a["date"], "pnl": g["pnl"], "outcome": g["outcome"]} if g and g.get("pnl") is not None else None
    return out


def stats(trades: list[dict]) -> dict:
    p = [t["pnl"] for t in trades]
    if not p:
        return {"n": 0, "pnl": None, "win": None}
    w = sum(x > 0 for x in p)
    return {"n": len(p), "pnl": round(sum(p) / len(p), 3), "win": round(w / len(p) * 100, 1), "sum": round(sum(p), 2)}


def split(trades: list[dict], cut: str) -> tuple[list, list]:
    return [t for t in trades if t["date"] <= cut], [t for t in trades if t["date"] > cut]


def judge(base: list[dict], cand: list[dict], cut: str) -> dict | None:
    """기준·후보 거래 목록 → 앞 70%(고르기)·뒤 30%(확인) 모두 좋아졌으면 결과, 아니면 None"""
    bt, bh = split(base, cut)
    ct, ch = split(cand, cut)
    sb_, sc_, hb, hc = stats(bt), stats(ct), stats(bh), stats(ch)
    if len(cand) < MIN_TRADES or len(cand) < MIN_KEEP * len(base) or not sc_["n"] or not hc["n"]:
        return None
    if sc_["pnl"] - (sb_["pnl"] or 0) < MIN_GAIN or hc["pnl"] < (hb["pnl"] or 0):
        return None
    return {"train": {"base": sb_, "new": sc_}, "holdout": {"base": hb, "new": hc}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=40)
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s", datefmt="%H:%M:%S", stream=sys.stdout)
    logging.getLogger("stockeye").setLevel(logging.INFO)
    import multiprocessing as mp
    import os
    from concurrent.futures import ProcessPoolExecutor

    from stockeye.analysis import regime
    from stockeye.cloud.client import Supabase, enabled
    from stockeye.config import data_dir, load_config
    from stockeye.data.store import DataStore
    from stockeye.engine import daytrade as dt, params as pm

    cfg = load_config()
    store = DataStore(data_dir(cfg))
    oh = store.load("ohlcv")
    if oh is None or oh.empty:
        sys.exit("일봉 데이터가 없습니다 — 먼저 4_daily.bat")
    names = store.load("listing")
    mk = dict(zip(names["code"], names["market"])) if names is not None and "market" in names else {}
    idx_days = regime.from_frame(store.load("index"), keep=400)
    dates = [pd.Timestamp(d) for d in sorted(oh["date"].unique())]
    cache = data_dir(cfg) / "minute_cache"
    have = sorted(p.name for p in cache.iterdir() if p.is_dir() and len(p.name) == 8)[-args.days:]
    base_params = pm.defaults(dt)
    scores = pm.TUNABLE["entry_score"][1]

    samples = []
    for ds in have:
        day = pd.Timestamp(ds)
        if day not in dates:
            continue
        di = dates.index(day)
        if di < 31:
            continue
        prev = dates[di - 1]
        dkey = day.strftime("%Y-%m-%d")
        pcs = oh[oh["date"] == prev].set_index("code")["close"].to_dict()
        hist = oh[(oh["date"] <= prev) & (oh["date"] > prev - pd.Timedelta(days=45))]
        adrs = {c: dt.adr(g) for c, g in hist.groupby("code")}
        h30 = oh[oh["date"].isin(dates[di - 30:di])].groupby("code")["high"].max().to_dict()
        rebs = {m: regime.rebound(regime.prev_chg(idx_days, dkey, m), (idx_days.get(dkey) or {}).get(m)) for m in ("KOSPI", "KOSDAQ")}
        for f in (cache / ds).glob("*.parquet"):
            c = f.stem
            if pcs.get(c):
                samples.append({"path": str(f), "date": dkey, "code": c, "prev_close": float(pcs[c]), "adr": adrs.get(c),
                                "hi": h30.get(c), "reb": rebs.get(mk.get(c) if mk.get(c) in rebs else "KOSPI"), "scores": scores})
    if not samples:
        sys.exit("분봉 보관(data/minute_cache)이 없습니다")
    days = sorted({s["date"] for s in samples})
    cut = days[max(0, int(len(days) * TRAIN_FRAC) - 1)]
    print(f"샘플 {len(samples)}건 · {days[0]}~{days[-1]} ({len(days)}일) · 고르기 {days[0]}~{cut} / 확인 {cut} 이후")
    nw = args.workers or max(1, min(6, (os.cpu_count() or 2) - 1))
    ex = ProcessPoolExecutor(nw, mp_context=mp.get_context("spawn")) if nw > 1 else None

    def run(params: dict) -> dict:
        jobs = [{**s, "params": params} for s in samples]
        outs = list(ex.map(work, jobs, chunksize=16)) if ex else [work(j) for j in jobs]
        res: dict[str, list] = {}
        for o in outs:
            for k, v in (o or {}).items():
                if v:
                    res.setdefault(k, []).append(v)
        return res

    t0 = time.time()
    base_all = run({})
    base_cur = base_all.get("80.0") or []
    print(f"기준(지금 조건) {stats(base_cur)}  ({(time.time() - t0) / 60:.0f}분)")
    cands = []
    for s in scores:                                                 # 진입 점수는 한 번 계산한 결과에서 비교
        if s != base_params["entry_score"]:
            cands.append(("entry_score", s, base_all.get(str(s)) or []))
    for name, (_, vals, lo, hi) in pm.TUNABLE.items():              # 나머지: 인접 후보만 다시 계산
        if name == "entry_score":
            continue
        cur = base_params[name]
        order = sorted(set(vals) | {cur})
        i = order.index(cur)
        for v in (order[i - 1] if i > 0 else None, order[i + 1] if i + 1 < len(order) else None):
            if v is None:
                continue
            cands.append((name, v, run({name: v}).get("80.0") or []))
            print(f"  {name}={v}: {stats(cands[-1][2])}  ({(time.time() - t0) / 60:.0f}분)")
    if ex:
        ex.shutdown()

    good = []
    for name, v, tr in cands:
        j = judge(base_cur, tr, cut)
        if j:
            good.append({"param": name, "from": base_params[name], "to": v, **j})
    good.sort(key=lambda g: -(g["holdout"]["new"]["pnl"] - (g["holdout"]["base"]["pnl"] or 0)) - (g["train"]["new"]["pnl"] - (g["train"]["base"]["pnl"] or 0)))
    now = pd.Timestamp.now(tz="Asia/Seoul")
    prop = {"at": now.strftime("%Y-%m-%d %H:%M"), "version": dt.VERSION, "period": [days[0], days[-1]], "split": cut,
            "samples": len(samples), "base": stats(base_cur), "proposal": good[0] if good else None, "others": good[1:4],
            "tested": len(cands), "note": "제안만 — 승인 전에는 엔진에 반영 안 됨 (30_apply_params.bat)"}
    md = [f"# 당일단타 조건 제안 ({prop['at']})", f"- 기간 {days[0]}~{days[-1]} · 샘플 {len(samples)} · 기준 {prop['base']}",
          f"- 시험한 변경 {len(cands)}개 (한 번에 하나씩)"]
    if good:
        g = good[0]
        md += [f"## 제안: {g['param']} {g['from']} → {g['to']}",
               f"- 고르기 구간 평균 손익 {g['train']['base']['pnl']}% → {g['train']['new']['pnl']}% (거래 {g['train']['base']['n']}→{g['train']['new']['n']})",
               f"- 확인 구간 평균 손익 {g['holdout']['base']['pnl']}% → {g['holdout']['new']['pnl']}% (거래 {g['holdout']['base']['n']}→{g['holdout']['new']['n']})",
               "- 반영: scripts_win\\30_apply_params.bat"]
    else:
        md.append("## 제안 없음 — 지금 조건보다 두 구간 모두 나은 변경이 없음")
    text = "\n".join(md)
    print("\n" + text)
    out = data_dir(cfg) / "weekly"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{now:%Y%m%d}.md").write_text(text, encoding="utf-8")
    (out / "proposal.json").write_text(json.dumps(prop, ensure_ascii=False, indent=1), encoding="utf-8")
    if enabled() and not args.dry_run:
        sb = Supabase()
        sb.upload(pm.PROPOSAL, json.dumps(prop, ensure_ascii=False).encode("utf-8"), "application/json")
        from stockeye.cloud import publish as pub
        pub.publish_status(sb, "engine_proposal", prop)
        print("Storage·status 에 제안 저장")


if __name__ == "__main__":
    main()
