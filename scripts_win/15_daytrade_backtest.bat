@echo off
chcp 65001 >nul
cd /d %~dp0..\backend
call .venv\Scripts\activate
rem 당일단타 되돌려 보기 (과거 1분봉). 처음엔 --check 로 KIS 과거 분봉이 되는지 확인:  15_daytrade_backtest.bat --check
rem 기본: 최근 20거래일 · 전날 거래대금 상위 80종목 (20~25분). 결과는 앱 검증 탭 당일단타에 올라갑니다.
python -m scripts.daytrade_backtest %*
echo.
pause
