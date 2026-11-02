@echo off
chcp 65001 >nul
cd /d %~dp0..\backend
call .venv\Scripts\activate
rem 당일단타 케이스 비교 (11개 전략을 같은 기간·종목풀에서 한꺼번에). 먼저 4_daily.bat 로 최근 일봉·수급을 받아 두세요. 22번과 동시에 돌리지 마세요(KIS 키 공유).
rem 기본: 최근 20거래일 · 전날 거래대금 상위 80  (15번을 돌린 기간이면 분봉 캐시를 써서 몇 분)  예) 24_daytrade_cases.bat --days 30 --only F1,V1
python -m scripts.daytrade_cases %*
echo.
pause
