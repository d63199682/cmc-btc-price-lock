@echo off
cd /d %~dp0
call .venv\Scripts\activate.bat
py -m uvicorn app.main:APP --reload --host 0.0.0.0 --port 8000
pause
