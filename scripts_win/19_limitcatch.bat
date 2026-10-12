@echo off
chcp 65001 >nul
cd /d %~dp0..\backend
call .venv\Scripts\activate
rem [limitcatch] weekdays 09:05-15:20, every minute. Details: backend\scripts\limitcatch.py
rem   auto start: run 18_auto_schedule.bat once (Mon-Fri 08:55)
rem   (comments are ASCII only: Korean text after chcp 65001 can break cmd parsing)
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
