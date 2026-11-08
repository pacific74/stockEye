"""엔진 파라미터 (2026-11-09) — 당일단타 조건을 코드 상수 대신 Storage 'engine/params.json' 에서 읽어 바꿀 수 있게.

  기본값 = engine/daytrade.py 의 상수. params.json 에 값이 있으면 덮어씀 (허용 범위 밖이면 무시).
  바꾸는 길은 하나: 주간 최적화가 '제안' → 사용자가 승인 → scripts/apply_params.py 가 params.json 저장 (이력 남김).
  파일 형식: {"version": N, "params": {이름: 값}, "history": [{"at","version","params","note"}]}
"""
from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)
PATH = "engine/params.json"
PROPOSAL = "engine/proposal.json"

# 이름: (daytrade 모듈 상수, 후보값, 하한, 상한) — 한 번에 하나씩 바꿔 비교할 대상
TUNABLE = {
    "entry_score": ("PRIORITY", [75.0, 78.0, 80.0, 83.0, 85.0], 70.0, 90.0),
    "vwap_chase": ("VWAP_CHASE", [0.02, 0.025, 0.03, 0.04, 0.05], 0.01, 0.07),
    "min_value": ("MIN_VALUE", [5e8, 10e8, 20e8, 30e8], 3e8, 50e8),
    "min_adr": ("MIN_ADR", [0.04, 0.05, 0.06, 0.07], 0.03, 0.10),
    "max_stop": ("MAX_STOP", [0.02, 0.025, 0.03, 0.04], 0.015, 0.05),
    "min_t1": ("MIN_T1", [0.02, 0.025, 0.03, 0.04], 0.015, 0.05),
    "min_t2": ("MIN_T2", [0.04, 0.05, 0.06, 0.07], 0.03, 0.09),
}


def defaults(dt) -> dict:
    return {k: getattr(dt, v[0]) for k, v in TUNABLE.items()}


def valid(name: str, value) -> bool:
    t = TUNABLE.get(name)
    try:
        return bool(t) and t[2] <= float(value) <= t[3]
    except (TypeError, ValueError):
        return False


def apply(dt, params: dict | None) -> dict:
    """params 를 daytrade 모듈 상수에 적용 → 실제 적용된 {이름: 값}"""
    done = {}
    for k, v in (params or {}).items():
        if valid(k, v):
            setattr(dt, TUNABLE[k][0], float(v))
            done[k] = float(v)
        else:
            log.warning("엔진 파라미터 무시: %s=%r", k, v)
    return done


class Overrides:
    """with Overrides(dt, {이름: 값}): ... — 끝나면 원래 값으로 (되돌려 보기에서 한 번에 하나씩 바꿔 볼 때)"""
    def __init__(self, dt, params: dict):
        self.dt, self.params, self.old = dt, params, {}

    def __enter__(self):
        for k, v in self.params.items():
            a = TUNABLE[k][0]
            self.old[a] = getattr(self.dt, a)
            setattr(self.dt, a, float(v))
        return self

    def __exit__(self, *exc):
        for a, v in self.old.items():
            setattr(self.dt, a, v)


def load(sb) -> dict:
    try:
        return json.loads(sb.download(PATH) or b"{}")
    except Exception as e:  # noqa: BLE001
        log.warning("engine/params.json 읽기 실패: %s", e)
        return {}


def save(sb, params: dict, note: str, at: str) -> dict:
    cur = load(sb)
    ver = int(cur.get("version") or 0) + 1
    merged = {**(cur.get("params") or {}), **{k: float(v) for k, v in params.items() if valid(k, v)}}
    hist = (cur.get("history") or []) + [{"at": at, "version": ver, "params": merged, "note": note}]
    obj = {"version": ver, "params": merged, "history": hist[-50:]}
    sb.upload(PATH, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json")
    return obj


def load_and_apply(sb, dt) -> dict:
    """실시간 엔진 시작 때: Storage 의 params 를 적용 (실패해도 기본값으로 계속)"""
    obj = load(sb)
    done = apply(dt, obj.get("params"))
    if done:
        dt.VERSION = f"{dt.VERSION}+p{obj.get('version')}"
        log.info("엔진 파라미터 v%s 적용: %s", obj.get("version"), done)
    return done
