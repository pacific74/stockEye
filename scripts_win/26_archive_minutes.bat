@echo off
chcp 65001 >nul
cd /d %~dp0..\backend
call .venv\Scripts\activate
rem Save 1-minute bars to data\minute_cache. Auto: 15:45 and at logon (catch-up). Manual: --back 20, --day 20261030
python -m scripts.archive_minutes %*
if /i "%1"=="auto" goto :eof
if /i "%1"=="logon" goto :eof
pause
