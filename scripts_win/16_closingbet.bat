@echo off
chcp 65001 >nul
cd /d %~dp0..\backend
call .venv\Scripts\activate
rem 종가배팅: 평일 오후 14:45 쯤 켜 두면 14:50~15:20 동안 1분마다 후보를 계산해 앱(관심 > 종가배팅, 메인)에 올리고
rem 15:20 마지막 회차의 매수 후보 3개를 저장합니다. 다음 날 저녁 배치가 결과(종가 매수 → 다음 날 오전 매도)를 검증 탭에 올립니다.
rem 매일 자동 실행: schtasks /create /tn "StockEye 종가배팅" /tr "%~f0" /sc weekly /d MON,TUE,WED,THU,FRI /st 14:45
python -m scripts.closingbet %*
echo.
pause
