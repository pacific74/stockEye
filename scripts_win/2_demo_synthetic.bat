@echo off
chcp 65001 >nul
cd /d %~dp0..\backend
call .venv\Scripts\activate
python -m scripts.collect --synthetic --n 400
python -m scripts.screen --detail 2
python -m scripts.backtest strategies\breakout_foreign.yaml
pause
