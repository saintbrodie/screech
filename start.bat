@echo off
echo =======================================================
echo Starting S.C.R.E.E.C.H. Backend Server...
echo =======================================================

cd "%~dp0backend"
IF EXIST "venv\Scripts\python.exe" (
    echo [INFO] Using virtual environment...
    venv\Scripts\python.exe -m uvicorn server:app --reload --host 0.0.0.0 --port 8000
) ELSE (
    echo [WARNING] No virtual environment found at venv\Scripts\python.exe
    echo Attempting to run with system python...
    python -m uvicorn server:app --reload --host 0.0.0.0 --port 8000
)

pause
