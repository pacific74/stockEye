@echo off
chcp 65001 >nul
cd /d %~dp0..\backend
call .venv\Scripts\activate
rem [record recommendations] put a past day's watch list into the recommendations table
rem   no option = today  /  --date 2026-10-12  /  --dry-run = count only
rem   run supabase\migrations\2026-10-12_recommendations.sql in Supabase SQL Editor first
python -m scripts.record_recommendations %*
echo.
pause
