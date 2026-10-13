@echo off
title StockEye - Limitcatch (09:05-15:20)
chcp 65001 >nul
cd /d %~dp0..\backend
call .venv\Scripts\activate
rem [limitcatch] weekdays 09:05-15:20, every minute. Details: backend\scripts\limitcatch.py
rem   daily auto start now uses 22_intraday.bat (daytrade + limitcatch together). Run this only for a manual single run.
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
