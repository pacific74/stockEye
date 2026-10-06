@echo off
chcp 65001 >nul
cd /d %~dp0..\backend
call .venv\Scripts\activate
rem 매일 18:00 이후 실행 (작업 스케줄러 등록 권장)
rem 1) 가격/수급/밸류/공시 증분 수집  2) (KIS 키 있으면) 프로그램매매  3) 오늘의 리포트 + AI 설명
python -m scripts.collect
if defined KIS_APP_KEY python -m scripts.collect --kis-program
python -m scripts.daily_report
