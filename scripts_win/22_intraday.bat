@echo off
title StockEye - Intraday (daytrade + limitcatch, realtime) 09:00-15:21
chcp 65001 >nul
cd /d %~dp0..\backend
call .venv\Scripts\activate
rem [intraday] daytrade + limitcatch in ONE process (replaces 14_daytrade.bat + 19_limitcatch.bat for daily use)
rem   locked (entry-met) stocks get KIS realtime ticks -> target/stop judged on every trade, app updates instantly
rem   buy/sell alerts go to the ADMIN ntfy topic only. No orders are placed.
rem   auto start: run 18_auto_schedule.bat once (Mon-Fri 08:50). Details: backend\scripts\intraday_live.py
rem   (comments are ASCII only: Korean text after chcp 65001 can break cmd parsing)
python -m pip show websocket-client >nul 2>&1 || python -m pip install -q websocket-client
if /i "%~1"=="auto" goto auto
python -m scripts.intraday_live %*
echo.
pause
goto :eof

:auto
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
if not exist ..\data\logs mkdir ..\data\logs
echo ===== %date% %time% ===== >> ..\data\logs\intraday.log
python -m scripts.intraday_live >> ..\data\logs\intraday.log 2>&1
