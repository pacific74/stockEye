@echo off
chcp 65001 >nul
cd /d %~dp0..\backend
call .venv\Scripts\activate
rem 종가배팅: 평일 오후 14:45 쯤 켜 두면 14:50~15:20 동안 1분마다 후보를 계산해 앱(관심 > 종가배팅, 메인)에 올리고
rem 15:20 마지막 회차의 매수 후보 3개를 저장합니다. 다음 날 저녁 배치가 결과(종가 매수 → 다음 날 오전 매도)를 검증 탭에 올립니다.
rem 매일 자동 실행: 18_auto_schedule.bat 을 한 번 실행 (월~금 14:45, PC 가 늦게 켜지면 켜졌을 때 바로 · 15:40 넘으면 건너뜀)
if /i "%~1"=="auto" goto auto
python -m scripts.closingbet %*
echo.
pause
goto :eof

:auto
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
if not exist ..\data\logs mkdir ..\data\logs
echo ===== %date% %time% ===== >> ..\data\logs\closingbet.log
python -m scripts.closingbet >> ..\data\logs\closingbet.log 2>&1
