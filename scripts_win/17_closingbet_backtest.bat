@echo off
chcp 65001 >nul
cd /d %~dp0..\backend
call .venv\Scripts\activate
rem 종가배팅 되돌려 보기.  --daily = 5년 일봉 (5~10분, 장 후반 매수세·뉴스 없이 환산)  /  --minutes 20 = 최근 20거래일 과거 1분봉 (KIS, 30분 안팎)
rem 아무 옵션 없으면 둘 다. 결과는 앱 검증 탭 종가배팅에 올라갑니다.
python -m scripts.closingbet_backtest %*
echo.
pause
