@echo off
rem Start Call Center Agent (Windows):  scripts\run.bat
cd /d "%~dp0\.."
if not exist .venv ( py -3 -m venv .venv || python -m venv .venv )
call .venv\Scripts\activate.bat
pip install -q -r backend\requirements.txt
if not exist .env copy .env.example .env >nul
cd backend
python run.py
pause
