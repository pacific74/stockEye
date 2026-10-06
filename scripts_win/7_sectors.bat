@echo off
chcp 65001 >nul
cd /d %~dp0..\backend
call .venv\Scripts\activate
rem KRX 업종 분류 수집 (다른 수집이 돌고 있어도 안전)
python -m scripts.collect --sectors-only
pause
