@echo off
chcp 65001 >nul
cd /d %~dp0..\backend
call .venv\Scripts\activate
rem 상한가포착 되돌려 보기.  --check = 과거 1분봉이 받아지는지 한 종목만 확인 (먼저 해 보세요)
rem   --minutes 20 = 최근 20거래일 과거 1분봉 (KIS, 10~30분) · 진입 가정 3가지 · 점수/도달 시각 구간별
rem   --daily = 5년 일봉 참고 (상한가 도달일 · 종가 잠김별 다음 날 시가, 1~3분)
rem 아무 옵션 없으면 --minutes 20 --daily. 결과는 앱 검증 탭 상한가포착에 올라갑니다.
python -m scripts.limitcatch_backtest %*
echo.
pause
