@echo off
REM 보드게임 games 폴더를 stockeye 프로젝트에 올리고 자동 배포합니다.
REM   push.bat            자동 커밋 메시지
REM   push.bat "메시지"   직접 메시지 입력
set "GAMES_ROOT=%~dp0"
set "GAMES_MSG=%~1"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=[IO.File]::ReadAllText($env:GAMES_ROOT+'deploy.ps1',[Text.Encoding]::UTF8); & ([scriptblock]::Create($s)) -Message $env:GAMES_MSG"
echo.
pause
