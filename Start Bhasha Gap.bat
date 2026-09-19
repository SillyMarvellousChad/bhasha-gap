@echo off
rem Double-click to start the Bhasha Gap dashboard. Close this window to stop it.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo First run: setting up Python environment, this takes a minute...
    python -m venv .venv || goto :error
    ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || goto :error
)

echo Starting Bhasha Gap... your browser will open automatically.
echo Keep this window open while you use the dashboard. Close it to stop.
".venv\Scripts\python.exe" -m streamlit run app.py --server.headless false
goto :eof

:error
echo.
echo Setup failed. Make sure Python is installed: https://www.python.org/downloads/
pause
