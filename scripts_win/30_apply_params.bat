@echo off
title StockEye - apply approved engine params
chcp 65001 >nul
cd /d %~dp0..\backend
call .venv\Scripts\activate
rem [apply_params] shows the weekly proposal and applies it only after you type y (use argument --reset to clear saved params)
python -m scripts.apply_params %*
echo.
pause
