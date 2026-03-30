@echo off
cd /d %~dp0
py -m venv .venv
call .venv\Scripts\activate.bat
py -m pip install -r requirements.txt
if not exist .env copy .env.example .env
echo.
echo Setup complete. Next, run run_windows.bat
echo.
pause
