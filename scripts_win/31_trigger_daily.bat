@echo off
title StockEye - wake GitHub daily batch
chcp 65001 >nul
cd /d %~dp0..\backend
call .venv\Scripts\activate
rem [trigger_daily] starts the GitHub daily-batch right away from this PC (GitHub schedule is often hours late)
rem   needs one line in backend\.env :  GH_DISPATCH_TOKEN=your_github_token  (fine-grained, this repo only, Actions: Read and write)
rem   run once with argument register to add a weekday 18:20 task to Task Scheduler
if /i "%~1"=="register" goto reg
if /i "%~1"=="auto" goto run
python -m scripts.trigger_daily
echo.
pause
goto :eof

:run
python -m scripts.trigger_daily >> ..\data\logs\trigger.log 2>&1
goto :eof

:reg
schtasks /create /tn "StockEye TriggerDaily" /tr "cmd.exe /c \"%~f0\" auto" /sc weekly /d MON,TUE,WED,THU,FRI /st 18:20 /f
pause
goto :eof
