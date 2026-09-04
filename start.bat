@echo off
setlocal
cd /d "%~dp0"

echo =======================================================
echo Starting S.C.R.E.E.C.H.
echo =======================================================

if exist ".venv\Scripts\python.exe" (
    echo [INFO] Using .venv
    ".venv\Scripts\python.exe" -m uvicorn backend.server:app --host 0.0.0.0 --port 8000
) else if exist "venv\Scripts\python.exe" (
    echo [INFO] Using venv
    "venv\Scripts\python.exe" -m uvicorn backend.server:app --host 0.0.0.0 --port 8000
) else (
    echo [WARNING] No project virtual environment found; using system Python.
    python -m uvicorn backend.server:app --host 0.0.0.0 --port 8000
)

pause
