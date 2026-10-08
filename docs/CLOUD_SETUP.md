# StockEye 클라우드 운영 설정 (PC 없이)

```
[GitHub Actions]  평일 18:40 일일 배치 · 토요일 백테스트          ← 해외 차단 시 [서울 VM] 으로 교체
      │  수집(KRX·DART·KIS) → 분석 → 발행
      ▼
[Supabase]  DB(리포트·후보·종목 상세·매매일지·주문) + 로그인 + Storage(5년치 원본 데이터)
      ▲
      │  로그인해서 직접 읽고 씀
[앱]  웹 https://stockeye.pages.dev  ·  안드로이드 APK (같은 주소/stockeye.apk)
[서울 VM] (선택) 장중 실시간 감시·알림·모의/반자동 매매 — 앱에서 승인하면 VM 이 주문
```

PC 는 **처음 한 번 5년치 데이터를 올릴 때만** 필요합니다. 이후는 꺼 둬도 됩니다.

---

## 1. Supabase 프로젝트 (15분)

1. https://supabase.com → New project (Region: **Northeast Asia (Seoul)**), DB 비밀번호는 아무거나 길게.
   Security 의 체크 3개(Enable Data API / Automatically expose new tables / Enable automatic RLS)는 **모두 켜기**.
2. **SQL Editor** → New query → `supabase/schema.sql` 내용 전체 붙여넣기 → **Run**.
3. **Project Settings → API Keys** 에서 복사
   - Project URL → `SUPABASE_URL`
   - `anon` `public` 키 → `SUPABASE_ANON_KEY` (앱에 들어가도 되는 공개 키)
   - `service_role` `secret` 키 → `SUPABASE_SERVICE_KEY` (**절대 앱·코드에 넣지 말 것** — setx·GitHub Secrets 에만)

### 1-1. 회원가입 + 이메일 인증 (가족·지인도 쓰도록)
| 위치 | 설정 |
|---|---|
| Authentication → **Sign In / Providers** | **Allow new users to sign up** 켜기 · Auth Providers 의 **Email** 켜기 · 그 안의 **Confirm email** 켜기 |
| Authentication → **URL Configuration** | **Site URL** = 웹 앱 주소 (예 `https://stockeye.pages.dev`) · **Redirect URLs** 에 `https://stockeye.pages.dev/**` 추가 |
| Project Settings → Authentication → **SMTP Settings** | 아래 "메일 보내기" 참고 (필수) |

**메일 보내기 (SMTP)** — Supabase 기본 메일은 프로젝트 팀원 주소로만, 시간당 몇 통만 보내므로
다른 사람의 인증 메일이 가지 않습니다. 무료로 Gmail 을 연결하세요.
1. Google 계정 → 보안 → **2단계 인증** 켜기 → **앱 비밀번호** 만들기 (16자리)
2. Supabase **SMTP Settings → Enable Custom SMTP** 켜고:
   - Sender email: 내 Gmail 주소 · Sender name: `StockEye`
   - Host: `smtp.gmail.com` · Port: `587` · Username: 내 Gmail 주소 · Password: 앱 비밀번호 16자리
3. (선택) Authentication → **Emails** 에서 메일 제목/내용을 한국어로 바꿀 수 있음

### 1-2. 내 계정 (관리자)
앱(웹)의 **회원가입** 으로 가입하고 메일 인증 → Authentication → Users 에서 내 이메일 클릭 → **User UID** 복사
→ `SUPABASE_USER_ID`. (실시간 감시·모의/반자동 주문은 이 계정 것만 처리합니다)
웹 앱이 아직 없으면 Users → Add user → Create new user (Auto Confirm User 체크) 로 먼저 만들어도 됩니다.

### 가입 승인 (관리자)
- 새로 가입한 사람은 메일 인증 후 로그인하면 **"관리자 승인을 기다리고 있어요"** 화면만 보입니다.
- 관리자(가장 먼저 가입한 계정 = 나)는 앱 홈 → 오른쪽 위 ⋮ → **회원 관리** 에서 승인/거절/승인 취소.
  홈 화면 맨 위에도 "가입 승인 대기 N명" 이 뜨고, 매일 저녁 리포트 알림에도 대기 인원이 붙습니다.
- 가입 즉시 휴대폰 알림을 받으려면 Supabase SQL Editor 에서 한 번:
  `insert into public.app_config values ('ntfy_topic', '내 ntfy 토픽') on conflict (key) do update set value = excluded.value;`
- 관리자를 바꾸려면 SQL Editor: `update public.profiles set is_admin = (email = '새관리자@메일');`

### 회원별 휴대폰 알림
- 각자 앱 홈 → ⋮ → **알림 설정**(승인 대기 화면에도 버튼 있음)에서 자기 ntfy 토픽을 저장하고 ntfy 앱에서 구독.
- 받는 알림: **가입 승인됨** · **매일 저녁 리포트 요약** · **내 보유종목 경고**(손절 검토/익절 검토/확인 필요). 각각 켜고 끌 수 있음.
- **장중 알림**(회원): '장중 매수 신호'(후보가 매수구간 진입, 참고용)와 '내 보유종목 손절가/목표가 도달'을 실시간으로.
  단, **장중 감시(scripts.monitor)가 돌고 있을 때만** 옵니다 — 서울 VM 또는 장중에 켜 둔 PC 에서 `9_monitor.bat`.
  주문 승인은 관리자 KIS 계좌 전용이라 회원에게는 없습니다.
- 관리자(나)는 GitHub Secret `NTFY_TOPIC` 으로 전체 리포트·가입 요청·주문 알림을 그대로 받음 (같은 토픽이면 중복 발송 안 함).

### 누가 무엇을 보나
- **모두 같이 보는 것**: 오늘의 시장 · 업종 · TOP10 · 전략 후보 · 종목 상세 · 백테스트 결과
- **각자 자기 것만**: 보유종목 · 매매일지 · 매매 분석 · 백테스트 요청 (한 사람당 대기 1건)
- **관리자만**: 장중 실시간 신호·주문(KIS 계좌 연결)
- 사용자 삭제: Authentication → Users → 해당 사용자 … → Delete user (그 사람 데이터도 함께 삭제)

## 2. PC 데이터를 Supabase 로 올리기 (최초 1회)

```bat
setx SUPABASE_URL https://xxxx.supabase.co
setx SUPABASE_SERVICE_KEY (service_role 키)
setx SUPABASE_USER_ID (User UID)
```
새 cmd 창에서 `scripts_win\12_cloud_push.bat` 실행 → `올리기 완료: 2x개 조각` 이 나오면 끝.
(5년치 약 170MB, 연도별로 쪼개서 올림. Supabase 무료 Storage 1GB 안에 충분)

## 3. GitHub 저장소 (코드 + 자동 실행)

1. https://github.com/new → 이름 `stockEye`, **Private** 로 생성
2. PC 에서 `scripts_win\13_github_push.bat` 실행 → 저장소 주소(https://github.com/아이디/stockEye.git) 입력
   (`data/`, 키, DB 파일은 `.gitignore` 로 올라가지 않음)
3. 저장소 **Settings → Secrets and variables → Actions → New repository secret** 에 하나씩:

| 이름 | 값 | 필수 |
|---|---|---|
| `SUPABASE_URL` | Project URL | ✅ |
| `SUPABASE_SERVICE_KEY` | service_role 키 | ✅ |
| `SUPABASE_USER_ID` | User UID | ✅ |
| `SUPABASE_ANON_KEY` | anon 키 (앱 빌드용) | ✅ |
| `KRX_ID`, `KRX_PW` | KRX 정보데이터시스템 계정 | ✅ |
| `DART_API_KEY` | DART 키 | 권장 |
| `KIS_APP_KEY`, `KIS_APP_SECRET` | 한국투자 Open API | 선택 (프로그램매매) |
| `NTFY_TOPIC` (+`NTFY_SERVER`) 또는 `TELEGRAM_BOT_TOKEN`·`TELEGRAM_CHAT_ID` | 휴대폰 알림 | 선택 |
| `ANTHROPIC_API_KEY` | AI 설명 | 선택 |
| `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` | 웹 배포 (4번) | 웹 쓰면 ✅ |

## 4. 해외 접속 점검 (중요)

GitHub Actions 서버는 미국에 있습니다. KRX·KIS 가 해외 IP 를 막으면 수집이 안 됩니다.
저장소 **Actions → net-check → Run workflow** → 끝나면 로그 맨 아래:

```
✅ KRX (pykrx)    2026-10-06 시세 2870종목 …
✅ DART           …
✅ Supabase       …
```
- **모두 ✅** → GitHub Actions 로 운영 (5번으로)
- **KRX 또는 KIS ❌** → 서울 VM 으로 운영 (`deploy/vm/README.md`) — 코드는 같고 실행 장소만 다름

## 5. 첫 배치 실행

**Actions → daily-batch → Run workflow** (처음엔 `수집 없이` 체크 안 해도 됨) → 5~15분.
끝나면 Supabase **Table Editor → daily_reports** 에 오늘 날짜가 생깁니다. 이후 평일 18:40 자동.
주간 백테스트: **Actions → weekly-backtest → Run workflow** 한 번 실행해 두면 앱 백테스트 화면이 채워집니다.

## 6. 앱 (웹 + 안드로이드)

### 웹 주소 만들기 — Cloudflare Pages (무료)
1. https://dash.cloudflare.com 가입 → 오른쪽 **Account ID** 복사 → Secret `CLOUDFLARE_ACCOUNT_ID`
2. **My Profile → API Tokens → Create Token → Custom token**
   권한: `Account` · `Cloudflare Pages` · `Edit` → 만들기 → Secret `CLOUDFLARE_API_TOKEN`
3. **Actions → app-build → Run workflow** (이후엔 app/ 코드가 바뀌어 push 될 때 자동)
4. 완료 화면 Summary 에 주소:
   - 웹: `https://stockeye.pages.dev` (이미 쓰인 이름이면 저장소 Variables 에 `PAGES_PROJECT` = 다른 이름)
   - 안드로이드: `https://stockeye.pages.dev/stockeye.apk` → 폰 브라우저에서 받아 설치
     ("출처를 알 수 없는 앱 설치 허용" 필요, 업데이트도 같은 주소에서 다시 받아 설치)

휴대폰 브라우저로 웹 주소를 열고 **홈 화면에 추가** 하면 앱처럼 쓸 수 있습니다.
처음 쓰는 사람은 **회원가입 → 메일 인증 → 로그인**. Tailscale 은 더 이상 필요 없습니다.

> 웹/APK 파일은 누구나 받을 수 있지만, 데이터는 로그인한 본인만 볼 수 있습니다 (Supabase 보안 규칙).
> 앱 안에는 공개용 anon 키만 들어갑니다.

## 7. (선택) 장중 실시간 감시 · 모의/반자동 매매

GitHub Actions 는 장중 30초 감시에 맞지 않습니다. 서울 VM 에서 `scripts.monitor` 가 돌면:
- 진입/손절/목표 신호 → 휴대폰 알림
- `trading.mode: paper` → 모의 체결이 매매일지(앱의 '일지')에 자동 기록
- `trading.mode: semi_auto` → 앱 '승인 대기 주문'에서 승인 → VM 이 현재가를 다시 확인하고 주문
실전 주문은 여전히 `allow_real_orders: false` 가 기본입니다.

## 스키마 변경분
`supabase/schema.sql` 은 언제나 전체본(처음부터 실행해도, 여러 번 실행해도 안전)이고,
그 뒤 바뀐 부분만 `supabase/migrations/날짜_내용.sql` 로 따로 둡니다. 이미 전체본을 실행했다면 새 마이그레이션 파일만 실행하면 됩니다.

| 파일 | 내용 |
|---|---|
| `2026-10-07_member_notify.sql` | 회원별 휴대폰 알림 |
| `2026-10-08_live_quotes.sql` | 메인 화면 '지금 시세' (Supabase 가 네이버 실시간 시세를 대신 받아 20초 캐시, `http` 확장 사용) |
| `2026-10-08_backtest_admin_only.sql` | 백테스트 요청은 관리자만 (앱의 백테스트 메뉴도 관리자에게만 보임) |

## 무엇이 어디서 바뀌었나

| 예전 (PC 서버) | 지금 (클라우드) |
|---|---|
| 앱 → PC FastAPI | 앱 → Supabase 직접 (로그인) |
| 종목 상세·비슷한 패턴 즉석 계산 | 매일 배치가 전 종목 상세 미리 계산 (비슷한 패턴은 후보 종목만) |
| 백테스트 즉석 실행 | 앱에서 '요청' → 다음 배치(평일 저녁/토요일)가 실행 → 결과 표시 |
| 매매일지 SQLite (PC) | Supabase `positions`/`orders` (앱·배치·VM 공유) |
| 보유종목 점검 즉석 | 매일 저녁 배치 때 점검 (새로 추가한 종목은 '점검 대기') |
| 메인 화면 = 장 마감 분석 | 메인 화면 = 지금 시세(장중 1분 자동 갱신) + 참고로 지난 마감 분석 |

PC 의 기존 방식(5_server.bat + Tailscale)도 그대로 동작합니다. 앱을 `SUPABASE_URL` 없이 빌드하면 PC 서버를 씁니다.

## 문제 해결

| 증상 | 확인 |
|---|---|
| 앱: "아직 리포트가 없습니다" | Actions → daily-batch 실행 기록. 실패면 로그 확인 |
| 앱: 로그인 안 됨 | "메일 인증이 아직" → 인증 메일 링크 클릭. 메일이 안 오면 SMTP 설정·스팸함 확인 |
| 인증 메일 링크가 localhost 로 감 | URL Configuration 의 Site URL 을 웹 앱 주소로 |
| 배치: `Storage 에 데이터가 없습니다` | 2번(PC 데이터 올리기) 먼저 |
| 배치: KRX 단계 실패 | net-check → KRX ❌ 이면 서울 VM |
| 휴장일 | 배치가 "새 거래일 데이터가 없습니다" 하고 분석을 건너뜀 (정상) |
| GitHub 예약 실행이 늦음 | GitHub 사정으로 10~30분 늦을 수 있음 (정상) |
