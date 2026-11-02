@echo off
chcp 65001 >nul
cd /d %~dp0..\backend
call .venv\Scripts\activate
rem Sangsanga daum-nal bunbong gyuchik bigyo. Meonjeo 4_daily.bat. 22beon-gwa dongsi-e doljiman maseyo.
python -m scripts.limitup_minute %*
echo.
pause
