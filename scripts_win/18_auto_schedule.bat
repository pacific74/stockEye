@echo off
title StockEye - Register daily tasks
chcp 65001 >nul
rem Register weekday tasks in Windows Task Scheduler (run once, no admin rights needed)
rem   Mon-Fri 08:50  22_intraday.bat auto    (daytrade 09:00-10:00 + limitcatch 09:05-15:20, realtime)
rem   Mon-Fri 14:45  16_closingbet.bat auto  (14:50-15:20)
rem   old tasks "StockEye Daytrade" / "StockEye Limitcatch" are removed automatically
rem   if the PC was off at that time, the task runs right after logon (scripts exit by themselves after market close)
rem   logs: data\logs\intraday.log, closingbet.log
rem turn off:  18_auto_schedule.bat off
cd /d %~dp0
if /i "%~1"=="off" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0auto_schedule.ps1" -Off
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0auto_schedule.ps1"
)
echo.
pause
