@echo off
chcp 65001 >nul
rem 최초 1회: 5년치 수집 (영업일 약 1,250일 x 여러 호출 → 수 시간 소요. 중단돼도 다시 실행하면 이어서 받음)
rem 먼저 KRX 정보데이터시스템 계정: setx KRX_ID 아이디 / setx KRX_PW 비밀번호
rem 공시까지 받으려면 먼저: setx DART_API_KEY 발급받은키
cd /d %~dp0..\backend
call .venv\Scripts\activate
python -m scripts.collect --start 2021-01-01
pause
