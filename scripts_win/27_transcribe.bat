@echo off
chcp 65001 >nul
cd /d %~dp0..\backend
call .venv\Scripts\activate
rem Video to text (faster-whisper). Usage: 27_transcribe.bat "D:\stockPrj\test\lecture.mp4" [--model medium]
pip show faster-whisper >nul 2>&1 || pip install faster-whisper
python -m scripts.transcribe %*
pause
