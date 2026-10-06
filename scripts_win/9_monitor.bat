@echo off
chcp 65001 >nul
cd /d %~dp0..\backend
call .venv\Scripts\activate
rem 장중 실시간 감시 (평일 08:55 작업 스케줄러 등록 권장). 15:30 자동 종료
rem 모드는 backend\config\settings.yaml 의 trading.mode (alert / paper / semi_auto)
python -m scripts.monitor
