@echo off
chcp 65001 >nul
cd /d %~dp0..\backend
call .venv\Scripts\activate
rem 당일단타: 평일 아침 08:50~09:00 에 켜 두면 09:00~10:30 동안 1분마다 후보를 계산해 앱(관심 > 당일단타, 메인)에 올립니다.
rem 필요: setx KIS_APP_KEY / KIS_APP_SECRET / SUPABASE_URL / SUPABASE_SERVICE_KEY  (선택: NAVER_HUB_ID / NAVER_HUB_SECRET)
rem 주문은 하지 않습니다. 끝나면 오늘 신호를 저장하고, 저녁 배치가 결과를 매겨 검증 탭에 올립니다.
rem 매일 자동 실행: 작업 스케줄러에 등록 (관리자 권한 명령 프롬프트에서 한 번)
rem   schtasks /create /tn "StockEye 당일단타" /tr "%~f0" /sc weekly /d MON,TUE,WED,THU,FRI /st 08:50
python -m scripts.daytrade %*
echo.
pause
