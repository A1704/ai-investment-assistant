@echo off
cd /d "%~dp0"
set PYTHONPATH=.
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "scripts\daily_briefing.py"
) else (
    python "scripts\daily_briefing.py"
)
