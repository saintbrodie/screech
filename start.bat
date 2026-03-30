@echo off
echo =======================================================
echo Starting S.C.R.E.E.C.H. Backend Server...
echo =======================================================

cd "%~dp0backend"
IF EXIST "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
) ELSE (
    echo [WARNING] No virtual environment found at venv\Scripts\activate.bat
    echo Continuing anyway, but dependencies might be missing!
)

python -m uvicorn server:app --reload --host 0.0.0.0 --port 8000

pause
