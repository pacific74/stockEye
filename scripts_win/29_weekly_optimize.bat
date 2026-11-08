@echo off
title StockEye - weekly condition optimizer
chcp 65001 >nul
cd /d %~dp0..\backend
call .venv\Scripts\activate
rem [weekly_optimize] re-run past minute data with one condition changed at a time -> proposal only (nothing is applied)
rem   run once with argument register to add a Saturday 10:00 task to Task Scheduler
if /i "%~1"=="register" goto reg
if /i "%~1"=="auto" goto run
python -m scripts.weekly_optimize
echo.
pause
goto :eof

:run
python -m scripts.weekly_optimize >> ..\data\logs\weekly.log 2>&1
goto :eof

:reg
schtasks /create /tn "StockEye WeeklyOptimize" /tr "cmd.exe /c \"%~f0\" auto" /sc weekly /d SAT /st 10:00 /f
pause
goto :eof
