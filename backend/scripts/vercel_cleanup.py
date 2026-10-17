"""Vercel 예전 배포 자동 삭제 (2026-10-17) — 배포마다 사이트 전체(APK 포함)가 따로 저장돼 무료 저장 공간 10GB 가 차서

  python backend/scripts/vercel_cleanup.py --project stockeye --days 3          # 3일 지난 배포 삭제
  python backend/scripts/vercel_cleanup.py --project stockeye --days 3 --dry-run
  · 지금 연결된 배포(production 주소가 가리키는 것)는 절대 지우지 않음
  · 토큰: 환경변수 VERCEL_TOKEN (GitHub Secrets). 표준 라이브러리만 사용
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.vercel.com"


def call(method: str, path: str, token: str, params: dict | None = None) -> dict:
    q = {k: v for k, v in (params or {}).items() if v is not None}
    url = f"{API}{path}" + (f"?{urllib.parse.urlencode(q)}" if q else "")
    req = urllib.request.Request(url, method=method, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read()
        return json.loads(body) if body else {}


def find_project(name: str, token: str) -> tuple[dict, str | None]:
    """프로젝트 이름 → (프로젝트, teamId). 개인 계정 먼저, 없으면 소속 팀마다"""
    scopes: list[str | None] = [None]
    try:
        scopes += [t["id"] for t in call("GET", "/v2/teams", token).get("teams", [])]
    except urllib.error.HTTPError:
        pass
    for team in scopes:
        try:
            return call("GET", f"/v9/projects/{urllib.parse.quote(name)}", token, {"teamId": team}), team
        except urllib.error.HTTPError:
            continue
    raise SystemExit(f"Vercel 프로젝트 '{name}' 을 찾지 못함")


def old_deployments(project: dict, team: str | None, token: str, days: float) -> list[dict]:
    """days 일보다 오래된 배포 (production 주소가 가리키는 배포는 뺌)"""
    keep = set()
    for t in (project.get("targets") or {}).values():          # 지금 연결된 배포 (production 등)
        if isinstance(t, dict) and t.get("id"):
            keep.add(t["id"])
    try:                                                       # 안전장치: 가장 최근 성공한 production 배포도 항상 남김
        latest = call("GET", "/v6/deployments", token, {"projectId": project["id"], "teamId": team, "limit": 1,
                                                       "target": "production", "state": "READY"}).get("deployments") or []
        keep |= {d["uid"] for d in latest}
    except urllib.error.HTTPError:
        if not keep:
            raise SystemExit("지금 연결된 배포를 확인하지 못해 아무것도 지우지 않음")
    if not keep:
        raise SystemExit("지금 연결된 배포를 확인하지 못해 아무것도 지우지 않음")
    cut = int((time.time() - days * 86400) * 1000)
    out, until = [], cut
    for _ in range(50):                                        # 100개씩 최대 5000개
        js = call("GET", "/v6/deployments", token, {"projectId": project["id"], "teamId": team, "limit": 100,
                                                     "until": until})
        deps = js.get("deployments") or []
        out += [d for d in deps if d.get("uid") not in keep and (d.get("created") or 0) < cut]
        nxt = (js.get("pagination") or {}).get("next")
        if not deps or not nxt:
            break
        until = nxt
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=os.getenv("PAGES_PROJECT") or "stockeye")
    ap.add_argument("--days", type=float, default=3)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    token = os.getenv("VERCEL_TOKEN")
    if not token:
        print("VERCEL_TOKEN 없음 → 건너뜀")
        return 0
    project, team = find_project(a.project, token)
    old = old_deployments(project, team, token, a.days)
    print(f"프로젝트 {a.project}: {a.days:g}일 지난 예전 배포 {len(old)}개" + (" (지우지 않고 보기만)" if a.dry_run else ""))
    gone = 0
    for d in old:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime((d.get("created") or 0) / 1000))
        if a.dry_run:
            print(f"  - {when} {d.get('url')}")
            continue
        try:
            call("DELETE", f"/v13/deployments/{d['uid']}", token, {"teamId": team})
            gone += 1
        except urllib.error.HTTPError as e:
            print(f"  ⚠ {when} {d.get('url')} 삭제 실패: {e.code}")
    if not a.dry_run:
        print(f"삭제 {gone}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
