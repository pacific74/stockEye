"""승인한 제안을 엔진 파라미터로 반영 — scripts_win/30_apply_params.bat

  python -m scripts.apply_params            # data/weekly/proposal.json 의 제안 1개를 보여주고 y 를 눌러야 반영
  python -m scripts.apply_params --reset    # 저장된 파라미터를 모두 지움 (코드 기본값으로)
  반영하면 Storage engine/params.json 에 이력과 함께 저장 → 다음 22_intraday 실행부터 적용 (실행 중이면 재시작)
"""
from __future__ import annotations

import argparse
import json
import sys

import pandas as pd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args()
    from stockeye.cloud.client import Supabase, enabled
    from stockeye.config import data_dir, load_config
    from stockeye.engine import params as pm
    if not enabled():
        sys.exit("Supabase 설정이 없습니다")
    sb = Supabase()
    now = pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d %H:%M")
    cur = pm.load(sb)
    print("지금 저장된 파라미터:", cur.get("params") or "(없음 — 코드 기본값)")
    if a.reset:
        sb.upload(pm.PATH, json.dumps({"version": int(cur.get("version") or 0) + 1, "params": {}, "history": (cur.get("history") or [])[-49:] + [
            {"at": now, "params": {}, "note": "초기화"}]}, ensure_ascii=False).encode("utf-8"), "application/json")
        print("초기화 완료")
        return
    f = data_dir(load_config()) / "weekly" / "proposal.json"
    prop = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    g = prop.get("proposal")
    if not g:
        sys.exit("반영할 제안이 없습니다")
    print(f"제안({prop.get('at')}): {g['param']} {g['from']} → {g['to']}")
    print(f"  고르기 {g['train']['base']['pnl']}% → {g['train']['new']['pnl']}% · 확인 {g['holdout']['base']['pnl']}% → {g['holdout']['new']['pnl']}%")
    if not a.yes and input("반영할까요? (y/N) ").strip().lower() != "y":
        print("취소")
        return
    obj = pm.save(sb, {g["param"]: g["to"]}, f"주간 제안 승인: {g['param']} {g['from']}→{g['to']}", now)
    print(f"반영 완료 — 엔진 파라미터 v{obj['version']}: {obj['params']}")


if __name__ == "__main__":
    main()
