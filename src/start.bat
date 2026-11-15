@echo off
rem Start the OrbitalPulse demo: backend, crew simulator, and all three views in the browser.
rem Double-click this file, or run start.bat from a terminal. Extra options are passed
rem through, e.g. start.bat --storm. Ctrl+C stops everything.
cd /d "%~dp0"

set PY=backend\.venv\Scripts\python.exe
if not exist "%PY%" (
  echo First run: creating backend\.venv and installing dependencies ...
  python -m venv backend\.venv || goto :error
  "%PY%" -m pip install -q -r evidence\requirements.txt || goto :error
)

"%PY%" run_demo.py %*
goto :eof

:error
echo Setup failed. Install Python 3.11 or newer and try again.
pause
