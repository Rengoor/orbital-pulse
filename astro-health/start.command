#!/usr/bin/env bash
# Start the AstroHealth demo: backend, crew simulator, and all three views in the browser.
# Double-click this file in Finder, or run ./start.command from a terminal.
# Extra options are passed through, e.g. ./start.command --storm
# Ctrl+C (or closing the window) stops everything.
set -e
cd "$(dirname "$0")"

PY=backend/.venv/bin/python
if [ ! -x "$PY" ]; then
  echo "First run: creating backend/.venv and installing dependencies ..."
  python3 -m venv backend/.venv
  "$PY" -m pip install -q -r evidence/requirements.txt
fi

exec "$PY" run_demo.py "$@"
