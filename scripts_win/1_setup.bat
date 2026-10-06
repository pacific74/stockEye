@echo off
chcp 65001 >nul
cd /d %~dp0..\backend
python -m venv .venv
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
echo.
echo [완료] 다음: 2_demo_synthetic.bat (인터넷 없이 시험) 또는 3_collect_first.bat (실데이터 5년치)
pause
