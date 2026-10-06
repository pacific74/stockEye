# StockEye (주식눈)

국내 주식 전체(코스피/코스닥)를 매일 훑어서 **"오늘 사도 되는 종목"과 "얼마에 사고, 어디서 팔고, 어디서 자를지"**를 보여주는 시스템.
1단계는 AI 없이 **규칙 기반 종목 선정 엔진 + 미래참조를 차단한 백테스트**까지.

```
국내 주식 전체 (코스피/코스닥 ~4,000)
        │
[데이터 수집 서버]  backend/stockeye/data       pykrx(KRX) · DART 공시
  가격/거래량 OHLCV · 투자자별 순매수 · 밸류에이션 · 공시
        │
[분석 엔진]        backend/stockeye/engine
  1차 필터 (~4,000 → ~500)  거래대금 20억↑ · 1,000원↑ · 관리/정지 제외 · 급락 제외
  2차 필터 (~500 → 50~100)  5>20일선 · 20일선 상승 · 현재가>20일선 · 거래량 · 돌파 · RSI · MACD · BB · ATR
  100점 종합점수            추세20 거래량15 거래대금10 수급20 돌파15 변동성5 재무5 뉴스10
  매매계획                  매수구간 · 1/2차 목표 · 손절 · 손익비 · 근거 · 주의 · 판정
        │
[백테스트 검증]     backend/stockeye/backtest
  T일 18:00 신호 → T+1 시가 체결 · 수수료+세금+슬리피지 · 미래참조 자동 감사 · 표본 외 검증
        │
[API 서버]          backend/api  (FastAPI)
        │
[Flutter 앱]        app/         매수 후보 → 종목 상세 → 백테스트
```

## ☁ 클라우드 운영 (PC 없이) — 권장

PC 를 켜 두지 않아도 매일 자동으로 돌고, 휴대폰·PC 어디서나 로그인해서 봅니다.
**설정 방법: [docs/CLOUD_SETUP.md](docs/CLOUD_SETUP.md)**

| 역할 | 어디서 | 파일 |
|---|---|---|
| 평일 18:40 수집·분석·발행 | GitHub Actions (또는 서울 VM) | `.github/workflows/daily.yml` · `backend/scripts/cloud_daily.py` |
| 토요일 5년 백테스트 | GitHub Actions | `weekly_backtest.yml` · `scripts/cloud_backtest.py` |
| DB · 로그인 · 원본 데이터 | Supabase | `supabase/schema.sql` · `stockeye/cloud/` |
| 앱 (웹 + 안드로이드) | Cloudflare Pages | `app-build` 워크플로 (`app.yml`) |
| 장중 감시·모의/반자동 매매 | 서울 VM (선택) | `deploy/vm/` |
| 해외 접속 점검 | GitHub Actions 수동 | `net_check.yml` · `scripts/net_check.py` |

아래 "빠른 시작"은 PC 에서 직접 돌리는 방식입니다 (최초 5년치 수집, 개발·시험용).

## 빠른 시작 (Windows)

| 순서 | 파일 | 내용 |
|---|---|---|
| 1 | `scripts_win\1_setup.bat` | 가상환경 + 패키지 설치 (Python 3.11 이상) |
| 2 | `scripts_win\2_demo_synthetic.bat` | **인터넷 없이** 가짜 데이터로 전체 흐름 시험 |
| 3 | `scripts_win\3_collect_first.bat` | 실데이터 5년치 수집 (최초 1회, 수 시간. 끊겨도 재실행하면 이어받음) |
| 4 | `scripts_win\4_daily.bat` | 매일 18시 이후: 증분 수집 + 오늘의 후보 |
| 5 | `scripts_win\5_server.bat` | 앱용 API 서버 (http://localhost:8000/docs) |
| 6 | `scripts_win\6_backtest.bat` | 예시 전략 + 엔진 자체 백테스트 |
| 12 | `scripts_win\12_cloud_push.bat` | (클라우드) PC 의 5년치 데이터를 Supabase 로 올리기 — 최초 1회 |
| 13 | `scripts_win\13_github_push.bat` | (클라우드) 코드를 GitHub 비공개 저장소에 올리기 |

**KRX 로그인 필요**: 최신 pykrx 는 KRX 정보데이터시스템(data.krx.co.kr) 계정으로 로그인해야 데이터를 준다.
회원가입 후 환경변수 등록 → `setx KRX_ID 아이디` / `setx KRX_PW 비밀번호` (새 창에서 적용).

공시(뉴스/공시 점수)를 쓰려면 [DART Open API](https://opendart.fss.or.kr) 키 발급 후 `setx DART_API_KEY 키값`.
없으면 뉴스/공시 항목은 빠지고 나머지 90점으로 100점 환산된다 (앱에 "데이터 없음"으로 표시).

### Flutter 앱
```bash
cd app
flutter create . --project-name stockeye --platforms=windows,android,web   # 플랫폼 폴더 생성 (최초 1회)
flutter pub get
dart run flutter_launcher_icons                                             # 앱 실행 아이콘 적용 (assets/icon)
flutter run -d windows                                                      # PC
flutter run -d emulator --dart-define=API_BASE=http://10.0.2.2:8000         # 안드로이드 에뮬레이터
```

## 미래참조(Look-ahead) 차단 — 3중 구조

1. **시점 고정 데이터 (`data/pit.py`)**
   모든 데이터에 '공개 시각'이 있다. `view(as_of)` 로 꺼내면 그 시각 이전에 공개된 것만 보인다.
   | 데이터 | D일 데이터 공개 시각 |
   |---|---|
   | 일봉 | D일 15:30 |
   | 투자자별 수급 · 밸류에이션 | D일 18:00 |
   | DART 공시 | 접수일 23:59 (시각 정보가 없어 보수적으로) |
   → `as_of=2025-10-10 09:30` 이면 10월 10일 일봉은 **존재하지 않는 것처럼** 처리. 미래 날짜를 요청하면 `FutureDataError` 로 즉시 중단.
2. **백테스트 시계 (`backtest/engine.py`)** — 가격표 접근이 '현재 날짜'를 넘으면 `FutureDataError`. 신호는 T일 18:00, 체결은 T+1 시가.
3. **자동 감사 (`backtest/lookahead.py`)** — 백테스트마다 실행
   - 절단 테스트: D일까지만 있는 데이터로 다시 계산한 지표 = 전체 데이터로 계산한 D일 지표?
   - 오염 테스트: D일 이후 값을 쓰레기로 바꿔도 D일 신호가 같은가?
   - 체결 순서: 모든 거래가 신호일 < 매수일 ≤ 매도일?
   - 코드 검사: `shift(-n)`, `center=True`, `bfill` 같은 미래참조 패턴이 소스에 없는가?
   테스트(`tests/test_core.py`)에 **일부러 내일 종가를 쓰는 버그**를 심어 감사가 잡아내는지 확인한다.

## 거래 비용 (`config/settings.yaml` → `costs`)
- 수수료 0.015% (매수/매도 각각) — 본인 증권사 수수료로 수정
- 증권거래세 0.20% (매도 시) — 2026년 기준 코스피 0.05%+농특세 0.15%, 코스닥 0.20%
- 슬리피지 0.10% (거래대금 50억 미만 종목 0.30%)
- 상한가 근처(+29%↑) 갭상승 시 매수 불가, 거래정지 중 매도 불가, 같은 날 손절·목표 동시 터치 시 손절 우선

## 백테스트 결과 읽는 법
- **표본 내 vs 표본 외**: 마지막 30% 기간은 따로 성적을 낸다. 표본 외가 크게 나쁘면 과최적화.
- **연도별**: 한 해(예: 2021 강세장)에만 몰려 번 전략은 위험.
- **감사 실패 시 결과를 믿지 말 것.**
- 합성 데이터는 무작위라서 어떤 전략도 의미 있게 이기지 못한다 → 합성 데이터에서 수익이 크게 나면 오히려 버그 신호.

## 알려진 한계 (다음 단계 과제)
- **생존편향**: 과거 시점의 관리종목/상장폐지 종목 목록이 없음 → 백테스트가 다소 낙관적일 수 있음. (상장폐지 이력 수집 필요)
- **프로그램 매매(종목별)**: pykrx 미제공 → 현재 비어 있음. 한국투자증권 KIS Open API 연동 시 추가.
- **실시간 신호**: 현재는 장 마감 후(일봉) 기준. 장중 신호는 KIS 실시간 시세 연동 단계에서.
- **재무**: KRX 일별 EPS/BPS/PER/PBR 사용. 분기 재무제표(DART)는 '공시일' 기준으로 붙여야 미래참조가 안 생김.
- 메모리: 4,000종목 × 5년 피처 ≈ 1~2GB (float32). RAM 16GB 이상 권장.

## 폴더 구조
```
backend/
  config/settings.yaml        필터·점수 가중치·매매계획·비용·백테스트 설정 (코드 수정 없이 조정)
  stockeye/data/              수집(pykrx, DART, 합성), 저장(parquet), 시점고정(PIT)
  stockeye/indicators.py      이동평균·RSI·MACD·볼린저·ATR (모두 인과적)
  stockeye/engine/            1·2차 필터, 100점 점수, 매매계획, 파이프라인
  stockeye/backtest/          엔진, 비용, 성과지표, 미래참조 감사, 전략
  strategies/*.yaml           백테스트 전략 정의
  scripts/                    collect / screen / backtest CLI
  stockeye/trading/           매매일지, 브로커(모의/KIS), 실시간 신호 엔진, 알림, 매매 분석
  api/main.py                 FastAPI
  tests/                      pytest (30개)
app/                          Flutter 앱 (lib/)
scripts_win/                  Windows 실행 배치 파일
```

---

## 2단계: AI 설명 · 전략 5종 · 업종 강도 · 유사 패턴 · 보유종목

```
Flutter 앱 ──(조회)──▶ Python API 서버 ──▶ data/reports/날짜.json (매일 18시 이후 생성)
     │                       │
     └──(로그인/보유/관심)──▶ Supabase ◀──(분석 결과 발행, 선택)── Python
                             │
                  KRX(pykrx) · DART · KIS Open API
```

| 기능 | 위치 | 설명 |
|---|---|---|
| 전략 5종 | `engine/strategies.py` | A 돌파 · B 눌림목 · C 거래량 폭발(급등 초기) · D 수급 · E 저평가+추세전환. 전략별 후보·판정·백테스트 |
| 오늘의 시장 | `analysis/market.py` | 지수 등락, 상승/하락 종목 수, 20일선 위 비율 → 🟢강세/🟡중립/🔴약세 |
| 돈이 몰리는 곳 | `analysis/market.py`, `config/themes.yaml` | 테마(직접 편집) + KRX 업종 강도 0~100 (등락·상승비율·거래대금 증가·수급·돌파 비율) |
| AI 설명 | `ai/explainer.py` | **AI = 판단 보조, 신호 = 통계/알고리즘.** AI는 계산된 숫자만 받아 문장으로 풀어 쓰고, 입력에 없는 숫자를 쓰면 자동으로 버리고 규칙 기반 문장으로 대체 |
| 비슷한 패턴 | `analysis/similar.py` | 최근 20일 모양이 비슷했던 과거 구간 + 그 뒤 5/10/20일 결과 **분포**. 결과가 기준일 이전에 끝난 구간만 사용 |
| 보유종목 | `portfolio.py` | 손절 이탈 · 목표 도달 · 20일선 이탈 · 보유기간 초과 · RSI 과열 알림 |
| KIS 연동 | `data/sources/kis_source.py` | 현재가, 종목별 프로그램매매(일별) — 조회 API만 사용, 주문 기능 없음 |
| Supabase | `../supabase/schema.sql`, `publish/supabase.py` | 사용자 테이블(RLS 본인만) + 분석 결과 테이블(서버만 쓰기) |

### 추가 키 (모두 선택 — 없으면 해당 기능만 빠짐)
| 환경변수 | 용도 | 없으면 |
|---|---|---|
| `ANTHROPIC_API_KEY` | AI 설명 ([console.anthropic.com](https://console.anthropic.com)) | 규칙 기반 문장 |
| `KIS_APP_KEY`, `KIS_APP_SECRET` | 프로그램매매, 실시간 현재가 | 수급 점수에서 프로그램 항목 제외 |
| `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` | 분석 결과 발행 (service_role 키는 서버 PC에만!) | 로컬 파일로만 저장 |
| `SUPABASE_USER_ID` | 서버가 Supabase 보유종목을 읽을 때 | `data/portfolio.json` 사용 |

### 매일 흐름
`4_daily.bat` = 증분 수집 → (KIS) 프로그램매매 → `daily_report` (시장·업종·TOP10·전략별 후보·AI 설명 → 저장 → Supabase)
업종 분류는 `7_sectors.bat` 로 한 번 받아두면 됨 (매일 수집 시 자동 갱신).

### 전략별 백테스트
`python -m scripts.backtest --all-strategies` → 전략별 승률·기대값·MDD·표본 외 성과 비교표.
결과는 `data/backtests/A.json` … 에 저장되어 앱 백테스트 화면에 비교표로 나온다.

---

## 3단계: 실시간 알림 → 모의투자 → 반자동 매매 + 자동 매매일지

| 단계 | 설정 (`settings.yaml` → `trading`) | 동작 |
|---|---|---|
| 3. 실시간 알림 | `mode: alert` | 전날 후보가 매수 적정구간에 들어오면 / 보유 종목이 손절·목표가에 닿으면 휴대폰 알림 |
| 4. 모의투자 | `mode: paper` | 신호가 나면 내부 모의계좌(기본 1,000만원)로 자동 체결 → 매매일지 자동 기록 |
| 5. 반자동 | `mode: semi_auto`, `broker: kis_vps` | 신호 → 알림 → 앱 **승인 대기**에서 승인 → KIS 모의투자 계좌로 지정가 주문 |
| 5. 반자동 (실전) | `broker: kis_prod`, **`allow_real_orders: true`** | 위와 같지만 실전 계좌. 기본은 꺼져 있음 |

안전장치: 1회 주문 금액 상한 · 최대 보유 종목 수 · 하루 매수 횟수 · 하루 손실 한도(넘으면 신규 진입 중지) ·
승인 대기 10분 만료 · 승인 순간 가격을 다시 확인해 매수구간을 벗어났으면 주문 안 함 · 상한가 근처 매수 금지 ·
손절도 기본은 승인 필요(`auto_stop_loss`) · 재생(시뮬레이션) 모드에서는 어떤 설정이든 실제 주문 불가.

**알림 받는 법** (둘 중 하나):
- 텔레그램: BotFather 로 봇 생성 → `setx TELEGRAM_BOT_TOKEN 토큰`, `setx TELEGRAM_CHAT_ID 내chatid`
- ntfy: 휴대폰에 ntfy 앱 설치 → 아무도 못 맞힐 토픽 이름 구독 → `setx NTFY_TOPIC 그토픽이름`

**KIS 주문용**: `setx KIS_ACCOUNT 12345678-01` (모의투자는 KIS 모의투자 앱키를 `KIS_APP_KEY/SECRET` 에)

**실행**: `9_monitor.bat` (평일 08:55 작업 스케줄러 등록 권장) · 키 없이 흐름 시험: `10_replay.bat`

### 매매일지 (자동)
`data/journal.db` (SQLite). 모의/KIS모의/실전/직접입력 매매가 모두 같은 형식으로 쌓인다.
- 매수 순간: 매수가 · 시각 · 당시 점수 · 전략 · 손절 · 목표1/2 · 매수 근거 · 주의사항 · 시장 분위기 · 테마
- 보유 중: 최대 손실폭(MAE) / 최대 수익폭(MFE) 계속 갱신
- 매도 후: 매도가 · 사유 · 수익률(비용 반영) · 보유기간 · 결과(성공/실패/본전) · 손절 지연 여부
- 직접 산 종목도 앱 **보유 → 추가**로 넣으면 그날 분석 스냅샷이 자동으로 붙는다. 팔면 **매도 기록**.

### 내 매매 분석 (앱 → 일지 → 내 매매 분석)
전략별 · 진입 시간대별(9:00~9:30 / ~11:00 / ~14:00 / 14시 이후) · 진입 점수별 · 시장 분위기별 · 보유기간별 ·
매도 사유별 · 요일별 승률/평균 수익률 + 손절 지연 · 목표가 찍고 놓친 매매 · 승인 지연 진단.
표본 20건 미만 칸은 `*` (우연일 수 있음). **AI 코치 요약**은 이 통계 숫자만 받아 쓰고, 통계에 없는 숫자를 쓰면 버려진다.

### 밖에서 휴대폰으로 보기 (Tailscale)
1. PC와 휴대폰에 Tailscale 설치 → 같은 계정으로 로그인 (무료, 둘만 연결되는 사설 네트워크)
2. `11_build_web.bat` 로 웹앱 빌드 → `5_server.bat` 실행
3. 휴대폰 브라우저에서 `http://PC이름:8000/app/` (PC이름은 Tailscale 앱에 표시) → 메뉴 → **홈 화면에 추가**
- 서버를 공유기 포트포워딩 등으로 인터넷에 직접 공개하지 말 것 (승인/주문 API 에 로그인 기능이 없음)
- PC가 켜져 있어야 함. PC 꺼져도 보려면 Supabase 단계로

## 다음 단계
- 공시 제목 키워드 점수(`engine/news.py`)를 AI 분류로 교체 (역시 신호가 아닌 보조 지표로)
- DART 재무제표(매출·영업이익) 연동 → 전략 E 보강
- KIS WebSocket 실시간 체결가 → 장중 신호
- Flutter 에서 Supabase 로그인 + 보유/관심종목 직접 읽기·쓰기

> 본 프로그램의 결과는 규칙 기반 분석이며 투자 권유가 아닙니다.
