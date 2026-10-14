@echo off
title StockEye - Intraday vs market/sector
chcp 65001 >nul
cd /d %~dp0..\backend
call .venv\Scripts\activate
rem [index compare] today's locked stocks: entry -> take-profit/stop, stock vs market(ETF) vs sector (all members, cap weighted)
rem   usage: 23_index_compare.bat              (daytrade)
rem          23_index_compare.bat --kind limitcatch
rem   result: screen + data\logs\index_compare_<date>_<kind>.csv  (paste the screen to Claude)
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
python -m scripts.index_compare %*
echo.
pause
