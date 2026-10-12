@echo off
chcp 65001 >nul
rem 당일단타·종가배팅을 윈도우 작업 스케줄러에 등록 (한 번만 실행하면 됨, 관리자 권한 필요 없음)
rem   월~금 08:50  14_daytrade.bat auto    (09:00~10:00)
rem   월~금 14:45  16_closingbet.bat auto  (14:50~15:20)
rem   PC 가 그 시각에 꺼져 있었으면 켜지고 로그인했을 때 바로 실행 (당일단타 10:00·종가배팅 15:40 지나면 그냥 끝냄)
rem   공휴일은 스크립트가 알아서 건너뜀. 기록: data\logs\daytrade.log · closingbet.log
rem 끄기:  18_auto_schedule.bat off
cd /d %~dp0
if /i "%~1"=="off" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0auto_schedule.ps1" -Off
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0auto_schedule.ps1"
)
echo.
pause
