#!/usr/bin/env bash
# 사용법: deploy/vm/run.sh daily|backtest|monitor|netcheck|update
# cron 에서 부르는 실행기: 환경변수 읽기 → 중복 실행 방지 → 로그 저장
set -uo pipefail
JOB="${1:?daily|backtest|monitor|netcheck|update}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ENV_FILE="${STOCKEYE_ENV:-$HOME/.stockeye.env}"
LOG_DIR="$HOME/stockeye-logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/$JOB-$(date +%Y%m%d-%H%M).log"
export TZ=Asia/Seoul PYTHONUTF8=1 STOCKEYE_RUNNER=vm
if [ -f "$ENV_FILE" ]; then set -a; . "$ENV_FILE"; set +a; else echo "환경변수 파일 없음: $ENV_FILE" >&2; exit 1; fi
cd "$ROOT/backend"
. .venv/bin/activate
case "$JOB" in
  daily)    LOCK=batch;    CMD="python -m scripts.cloud_daily" ;;
  backtest) LOCK=batch;    CMD="python -m scripts.cloud_backtest --only WEEKLY" ;;   # 적중률: 올해만 다시
  monitor)  LOCK=monitor;  CMD="python -m scripts.monitor"
            if [ -z "${KIS_APP_KEY:-}" ]; then echo "KIS 키 없음 → 장중 감시 생략"; exit 0; fi ;;
  netcheck) LOCK=netcheck; CMD="python -m scripts.net_check" ;;
  update)   LOCK=update;   CMD="bash -c 'cd $ROOT && git pull --ff-only && cd backend && pip install -q -r requirements.txt'" ;;
  *) echo "알 수 없는 작업: $JOB" >&2; exit 2 ;;
esac
# 같은 종류 작업이 이미 돌고 있으면 기다렸다가 실행 (배치·백테스트는 같은 잠금)
exec 9>"/tmp/stockeye-$LOCK.lock"
flock 9
echo "[$(date '+%F %T')] $JOB 시작" | tee -a "$LOG"
eval "$CMD" >>"$LOG" 2>&1
RC=$?
echo "[$(date '+%F %T')] $JOB 종료 (코드 $RC)" | tee -a "$LOG"
find "$LOG_DIR" -name '*.log' -mtime +30 -delete
exit $RC
