@echo off
chcp 65001 >nul
cd /d %~dp0..\backend
call .venv\Scripts\activate
uvicorn api.main:app --host 0.0.0.0 --port 8000
