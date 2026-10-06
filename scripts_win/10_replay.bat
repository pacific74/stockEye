@echo off
chcp 65001 >nul
cd /d %~dp0..\backend
call .venv\Scripts\activate
rem KIS 없이 과거 하루를 재생해서 알림/모의매매 흐름 시험 (실제 주문·휴대폰 알림 없음)
set /p D=재생할 날짜 (YYYY-MM-DD): 
python -m scripts.monitor --replay %D% --mode paper
pause
