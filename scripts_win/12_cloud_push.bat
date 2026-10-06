@echo off
chcp 65001 >nul
rem PC 의 5년치 원본 데이터를 Supabase Storage 로 올리기 (클라우드 운영 최초 1회)
rem 필요: setx SUPABASE_URL ... / setx SUPABASE_SERVICE_KEY ...
cd /d %~dp0..\backend
call .venv\Scripts\activate
if "%SUPABASE_URL%"=="" (echo [오류] SUPABASE_URL 환경변수가 없습니다. setx 후 새 창에서 실행하세요 & pause & exit /b 1)
if "%SUPABASE_SERVICE_KEY%"=="" (echo [오류] SUPABASE_SERVICE_KEY 환경변수가 없습니다 & pause & exit /b 1)
python -m scripts.cloud_push %*
echo.
echo [다음] GitHub 저장소 만들기: 13_github_push.bat
pause
