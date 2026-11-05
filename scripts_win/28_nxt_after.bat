@echo off
title StockEye - NXT after-market record
chcp 65001 >nul
cd /d %~dp0..\backend
call .venv\Scripts\activate
rem [nxt_after] record NXT after-market prices of all stocks (weekdays 19:30 and 20:05; if 20:05 has no data the 19:30 record is kept) -> next morning early picks use it
rem   run once with argument register to add the 19:30 and 20:05 weekday task to Task Scheduler
rem   (comments are ASCII only: Korean text after chcp 65001 can break cmd parsing)
if /i "%~1"=="register" goto reg
if /i "%~1"=="auto" goto run
python -m scripts.nxt_after
echo.
pause
goto :eof

:run
python -m scripts.nxt_after >> ..\data\logs\nxt_after.log 2>&1
goto :eof

:reg
schtasks /create /tn "StockEye NxtAfter" /tr "cmd.exe /c \"%~f0\" auto" /sc weekly /d MON,TUE,WED,THU,FRI /st 20:05 /f
schtasks /create /tn "StockEye NxtAfter1930" /tr "cmd.exe /c \"%~f0\" auto" /sc weekly /d MON,TUE,WED,THU,FRI /st 19:30 /f
pause
goto :eof
