@echo off
chcp 65001 >nul
cd /d %~dp0..\backend
call .venv\Scripts\activate
rem [limitcatch backtest] details: backend\scripts\limitcatch_backtest.py
rem   --check       : one stock, check past 1-min bars
rem   --minutes 20  : last 20 trading days of 1-min bars (KIS, 10-30 min)
rem   --daily       : 5-year daily reference (1-3 min)
rem   no option     : --minutes 20 --daily  (result -> app validation tab)
python -m scripts.limitcatch_backtest %*
echo.
pause
