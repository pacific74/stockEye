@echo off
chcp 65001 >nul
rem 코드를 GitHub 비공개 저장소에 올리기 (data 폴더·키·DB 는 .gitignore 로 제외됨)
cd /d %~dp0..
where git >nul 2>nul || (echo [오류] Git 이 없습니다. https://git-scm.com/download/win 설치 후 다시 실행 & pause & exit /b 1)
if not exist .git (
  git init
  git branch -M main
)
git config user.name >nul 2>nul || git config user.name "StockEye"
git config user.email >nul 2>nul || git config user.email "stockeye@localhost"
git remote get-url origin >nul 2>nul
if errorlevel 1 (
  set /p REPO=GitHub 저장소 주소 [예: https://github.com/아이디/stockEye.git]: 
)
if defined REPO git remote add origin %REPO%
git add -A
git status --short | findstr /r /c:"^.. data/" /c:"\.db$" /c:"\.env$" /c:"kis_token" && (echo [중단] 올리면 안 되는 파일이 보입니다. 위 목록 확인 & pause & exit /b 1)
git commit -m "StockEye 업데이트" || echo (바뀐 파일 없음)
git branch -M main
rem remote has newer commits (bots or other batches) -> merge first, then push
git pull --rebase --autostash origin main || (echo [오류] 원격 변경을 합치지 못했어요. 이 화면을 그대로 알려 주세요. & pause & exit /b 1)
git push -u origin main
echo.
echo [완료] GitHub 저장소 Settings - Secrets 에 키를 넣고 Actions 에서 net-check 실행
pause
