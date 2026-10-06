"""보유종목 관리.

보유종목 자체는 매매일지(열린 포지션)에 저장된다 (PC: SQLite, 클라우드: Supabase positions).
LocalRepo 는 예전 data/portfolio.json 호환용.

상태 점검 (매일 장 마감 후 데이터 기준):
  손절가 이탈 / 목표가 도달 / 20일선 이탈 / 보유기간 초과 / 오늘 엔진 점수·전략 태그
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pandas as pd


class LocalRepo:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _load(self) -> list[dict]:
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []

    def _save(self, rows):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

    def list(self):
        return self._load()

    def add(self, h: dict) -> dict:
        rows = self._load()
        h = {**h, "id": h.get("id") or uuid.uuid4().hex[:12]}
        rows.append(h)
        self._save(rows)
        return h

    def update(self, hid: str, patch: dict) -> dict | None:
        rows = self._load()
        for r in rows:
            if r["id"] == hid:
                r.update({k: v for k, v in patch.items() if k != "id"})
                self._save(rows)
                return r
        return None

    def delete(self, hid: str) -> bool:
        rows = self._load()
        new = [r for r in rows if r["id"] != hid]
        self._save(new)
        return len(new) != len(rows)


def review(holdings: list[dict], x: pd.DataFrame, as_of_date, report_index: dict | None = None,
           max_hold_days: int = 15) -> list[dict]:
    """보유종목 상태 점검. x = 최근일 피처 단면, report_index = 코드→(점수, 태그)."""
    report_index = report_index or {}
    out = []
    for h in holdings:
        code = h["code"]
        r = x.loc[code] if code in x.index else None
        item = {**h, "alerts": [], "status": "정상"}
        if r is None:
            item["alerts"].append("오늘 데이터 없음 (거래정지/상장폐지 확인)")
            item["status"] = "확인 필요"
            out.append(item)
            continue
        px = float(r["close"])
        avg = float(h.get("avg_price") or px)
        item.update({"price": int(px), "pnl_pct": round((px / avg - 1) * 100, 2),
                     "pnl": int((px - avg) * float(h.get("qty") or 0)),
                     "ret1_pct": round(float(r["ret1"]) * 100, 2) if pd.notna(r["ret1"]) else None})
        stop, target = h.get("stop"), h.get("target")
        if stop and float(r["low"]) <= float(stop):
            item["alerts"].append(f"손절가 {int(stop):,}원 이탈 (저가 {int(r['low']):,}원)")
            item["status"] = "손절 검토"
        if target and float(r["high"]) >= float(target):
            item["alerts"].append(f"목표가 {int(target):,}원 도달 (고가 {int(r['high']):,}원)")
            item["status"] = "익절 검토" if item["status"] == "정상" else item["status"]
        if pd.notna(r.get("sma20")) and px < float(r["sma20"]):
            item["alerts"].append(f"20일선({int(r['sma20']):,}원) 아래 마감")
            if item["status"] == "정상":
                item["status"] = "주의"
        if h.get("buy_date"):
            days = int(((pd.Timestamp(as_of_date) - pd.Timestamp(h["buy_date"])).days) * 5 / 7)
            item["hold_days"] = days
            if days > max_hold_days:
                item["alerts"].append(f"보유 약 {days}영업일 (전략 기준 {max_hold_days}일 초과)")
        if pd.notna(r.get("rsi14")) and r["rsi14"] >= 75:
            item["alerts"].append(f"RSI {r['rsi14']:.0f} 과열 → 분할 익절 고려")
        info = report_index.get(code)
        if info:
            item["today_score"], item["today_tags"] = info.get("score"), info.get("tags", [])
        out.append(item)
    return out
