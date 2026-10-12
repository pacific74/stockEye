@echo off
chcp 65001 >nul
cd /d %~dp0..\backend
call .venv\Scripts\activate
rem 상한가포착: 평일 09:00 쯤 켜 두면 09:05~15:20 동안 1분마다 +20% 이상 종목의 상한가 잠김·풀림·잔량을 계산해
rem 앱(관심 > 상한가포착, 메인)에 올립니다. 후보 찾기는 KIS 등락률 순위 1번 (전 종목 시세를 1분마다 받지 않음).
rem 1분마다 호가 기록을 data\limitcatch\ticks_날짜.jsonl 에 남기고 장 마감 뒤 Storage 로 올립니다 (잔량 항목 검증용).
rem 매일 자동 실행: 18_auto_schedule.bat 을 다시 한 번 실행 (월~금 08:55, PC 가 늦게 켜지면 켜졌을 때 바로 · 15:40 넘으면 건너뜀)
if /i "%~1"=="auto" goto auto
python -m scripts.limitcatch %*
echo.
pause
goto :eof

:auto
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
if not exist ..\data\logs mkdir ..\data\logs
echo ===== %date% %time% ===== >> ..\data\logs\limitcatch.log
python -m scripts.limitcatch >> ..\data\logs\limitcatch.log 2>&1
