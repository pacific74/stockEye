#!/usr/bin/env bash
# StockEye 서버 설치 (Ubuntu 22.04 / 24.04, 서울·춘천 리전 VM)
#   1) git clone 으로 저장소를 받은 뒤:  bash deploy/vm/setup.sh
#   2) ~/.stockeye.env 에 키 입력
#   3) bash deploy/vm/run.sh netcheck   → 모두 ✅ 인지 확인
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
echo "== StockEye 설치: $ROOT"

echo "== 시간대: 한국"
sudo timedatectl set-timezone Asia/Seoul || true

echo "== 패키지"
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip git util-linux

# 메모리가 4GB 미만이면 스왑 4GB (일일 배치가 최대 3.5GB 정도 씀)
MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
if [ "$MEM_MB" -lt 4000 ] && ! swapon --show | grep -q swapfile; then
  echo "== 메모리 ${MEM_MB}MB → 스왑 4GB 추가"
  sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi

echo "== 파이썬 가상환경"
cd "$ROOT/backend"
python3 -m venv .venv
. .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt

if [ ! -f "$HOME/.stockeye.env" ]; then
  cp "$ROOT/deploy/vm/stockeye.env.example" "$HOME/.stockeye.env"
  chmod 600 "$HOME/.stockeye.env"
  echo "== ~/.stockeye.env 를 만들었습니다. 키를 입력하세요:  nano ~/.stockeye.env"
fi
chmod +x "$ROOT/deploy/vm/run.sh"

echo "== 예약 작업(cron) 등록"
RUN="$ROOT/deploy/vm/run.sh"
TMP=$(mktemp)
crontab -l 2>/dev/null | grep -v 'deploy/vm/run.sh' > "$TMP" || true
cat >> "$TMP" <<CRON
# --- StockEye (setup.sh 가 관리) ---
40 18 * * 1-5 $RUN daily
50 8 * * 1-5 $RUN monitor
30 7 * * * $RUN update
# 백테스트는 메모리 8GB 이상일 때만 권장 (아니면 GitHub Actions 주간 백테스트 사용)
# 0 10 * * 6 $RUN backtest
CRON
crontab "$TMP"; rm -f "$TMP"
crontab -l | sed -n '/StockEye/,$p'

cat <<MSG

설치 끝.
  1) nano ~/.stockeye.env        (키 입력)
  2) bash $RUN netcheck && cat ~/stockeye-logs/netcheck-*.log | tail -15
  3) GitHub 저장소 → Settings → Secrets and variables → Actions → Variables 에
     BATCH_RUNNER = vm   (GitHub 의 일일 배치를 끄고 이 서버가 맡음)
  로그: ~/stockeye-logs/
MSG
