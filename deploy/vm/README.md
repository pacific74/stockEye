# 서울 리전 VM 에서 운영하기

GitHub Actions(미국)에서 KRX/KIS 접속이 막히거나, 장중 실시간 감시·모의/반자동 매매를 쓰려면
한국 리전의 리눅스 서버 한 대에서 같은 코드를 돌립니다.

## 서버 고르기
| | 메모리 | 비고 |
|---|---|---|
| Oracle Cloud Always Free (Ampere A1, **서울** 리전) | 2 OCPU · 12GB (2026.6 축소) | 무료. 자원이 모자라 생성이 잘 안 될 때가 많음, 7일간 한가하면 회수될 수 있음 |
| AWS Lightsail / EC2 서울, 네이버·KT 클라우드 등 | **4GB 이상** 권장 | 유료 (요금은 각 사이트 확인) |

- 일일 배치는 메모리를 최대 약 3.5GB 씁니다. 2GB 서버면 `setup.sh` 가 스왑 4GB 를 붙이지만 느립니다.
- 5년 백테스트는 약 5GB → 8GB 미만이면 백테스트는 GitHub Actions(주간) 에 그대로 맡기세요.
- OS: Ubuntu 22.04 또는 24.04

## 설치
```bash
# 1) 저장소 받기 (Private 저장소: GitHub → Settings → Developer settings → Personal access tokens
#    → Fine-grained, 이 저장소 Contents: Read-only 토큰)
git clone https://<토큰>@github.com/<아이디>/stockEye.git
cd stockEye

# 2) 설치 (시간대 KST, 파이썬, cron 등록)
bash deploy/vm/setup.sh

# 3) 키 입력
nano ~/.stockeye.env

# 4) 점검 — 모두 ✅ 인지
bash deploy/vm/run.sh netcheck; tail -15 ~/stockeye-logs/netcheck-*.log
```

## 등록되는 예약 작업 (cron, 한국 시간)
| 시각 | 작업 |
|---|---|
| 평일 18:40 | `daily` 수집 → 분석 → Supabase 발행 |
| 평일 08:50 | `monitor` 장중 감시 (KIS 키가 있을 때만, 15:30 자동 종료, 휴장일 자동 종료) |
| 매일 07:30 | `update` git pull (GitHub 에 올린 코드 자동 반영) |
| (주석) 토 10:00 | `backtest` — 메모리 8GB 이상이면 `crontab -e` 로 주석 해제 |

VM 이 일일 배치를 맡으면 GitHub 저장소 **Settings → Secrets and variables → Actions → Variables** 에
`BATCH_RUNNER` = `vm` 을 추가해서 GitHub 쪽 예약 실행을 끕니다 (둘이 같이 돌지 않게).
백테스트까지 VM 이 하면 `BACKTEST_RUNNER` = `vm`.

## 매매 모드 바꾸기
`backend/config/settings.yaml` 의 `trading.mode` (alert → paper → semi_auto) 를 바꿔 GitHub 에 push 하면
다음 날 아침 07:30 `update` 때 반영됩니다. 실전 주문(`allow_real_orders`)은 기본 꺼짐.

## 로그
`~/stockeye-logs/` (30일 지나면 자동 삭제)
