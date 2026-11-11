"""저녁 배치를 PC 에서 직접 깨우기 (2026-11-11) — GitHub 예약 실행이 몇 시간씩 늦는 날을 막으려고

  PC 작업 스케줄러가 평일 18:20 에 이걸 실행 → GitHub Actions 'daily-batch' 를 바로 시작 (workflow_dispatch)
  PC 가 꺼져 있으면 아무 일도 안 일어나고, 기존 GitHub 예약(18:10~21:10)이 그대로 백업.
  이미 발행된 날이면 배치가 1분 안에 '분석 생략' 으로 끝나므로 겹쳐도 안전.
  필요: backend/.env 에 GH_DISPATCH_TOKEN=... (GitHub fine-grained token · 이 저장소 · Actions: Read and write)
  python -m scripts.trigger_daily [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = "pacific74/stockEye"
WORKFLOW = "daily.yml"


def _token() -> str:
    t = os.environ.get("GH_DISPATCH_TOKEN", "").strip()
    if t:
        return t
    env = Path(__file__).resolve().parents[1] / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith("GH_DISPATCH_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def dispatch(token: str, repo: str = REPO, workflow: str = WORKFLOW, ref: str = "main", opener=urllib.request.urlopen) -> int:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/dispatches",
        data=json.dumps({"ref": ref}).encode(), method="POST",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "stockeye-trigger"})
    with opener(req, timeout=30) as r:
        return r.status


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    tok = _token()
    if not tok:
        print("GH_DISPATCH_TOKEN 이 없습니다 — backend\\.env 에 GH_DISPATCH_TOKEN=토큰 한 줄 추가 (31_trigger_daily.bat 안내 참고)")
        return 2
    if a.dry_run:
        print("토큰 확인됨 — 실제 호출은 --dry-run 을 빼고")
        return 0
    try:
        st = dispatch(tok, os.environ.get("GH_REPO", REPO))
        print(f"daily-batch 시작 요청 완료 (HTTP {st}) — GitHub Actions 탭에서 확인")
        return 0
    except urllib.error.HTTPError as e:
        print(f"실패 HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:300]}")
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"실패: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
