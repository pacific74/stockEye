@echo off
chcp 65001 >nul
cd /d %~dp0..\backend
call .venv\Scripts\activate
rem 수집 없이 오늘의 리포트만 다시 만들기
python -m scripts.daily_report
pause
