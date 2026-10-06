@echo off
chcp 65001 >nul
rem 휴대폰/다른 PC 브라우저용 웹앱 빌드 → 5_server.bat 가 http://PC주소:8000/app/ 로 내보냄
cd /d %~dp0..\app
flutter build web --release --base-href /app/
echo.
echo 완료. 5_server.bat 를 (다시) 켜고 휴대폰 브라우저에서 http://PC이름:8000/app/ 접속
pause
