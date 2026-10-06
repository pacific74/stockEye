@echo off
chcp 65001 >nul
cd /d %~dp0..\backend
call .venv\Scripts\activate
rem 전략 A~E 를 모두 백테스트하고 비교표 출력 (결과는 앱 백테스트 화면에도 표시)
python -m scripts.backtest --all-strategies
echo.
python -m scripts.backtest strategies\breakout_foreign.yaml
pause
