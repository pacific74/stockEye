@echo off
title StockEye - Daytrade (09:00-15:20)
chcp 65001 >nul
cd /d %~dp0..\backend
call .venv\Scripts\activate
rem 당일단타: 평일 아침 08:50~09:00 에 켜 두면 09:00~10:00 동안 1분마다 후보를 계산해 앱(관심 > 당일단타, 메인)에 올립니다.
rem 필요: setx KIS_APP_KEY / KIS_APP_SECRET / SUPABASE_URL / SUPABASE_SERVICE_KEY  (선택: NAVER_HUB_ID / NAVER_HUB_SECRET)
rem 주문은 하지 않습니다. 끝나면 오늘 신호를 저장하고, 저녁 배치가 결과를 매겨 검증 탭에 올립니다.
rem daily auto start now uses 22_intraday.bat (daytrade + limitcatch together). Run this only for a manual single run.
if /i "%~1"=="auto" goto auto
python -m scripts.daytrade %*
echo.
pause
goto :eof

:auto
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
rem 작업 스케줄러가 부를 때: 창을 기다리지 않고, 기록은 data\logs\daytrade.log
if not exist ..\data\logs mkdir ..\data\logs
echo ===== %date% %time% ===== >> ..\data\logs\daytrade.log
python -m scripts.daytrade >> ..\data\logs\daytrade.log 2>&1
