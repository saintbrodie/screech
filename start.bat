@echo off
setlocal
cd /d "%~dp0"

echo =======================================================
echo Starting S.C.R.E.E.C.H.
echo =======================================================

where deno >nul 2>&1
if errorlevel 1 (
    echo [WARNING] Deno was not found on PATH.
    echo           Current yt-dlp releases recommend Deno 2.3+ for full YouTube support.
    echo           Local fixture mode will still work. See YOUTUBE_SETUP.md.
)

where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo [WARNING] ffmpeg was not found on PATH.
    echo           Live extraction may be limited and timestamped fixture downloads need ffmpeg.
    echo           See YOUTUBE_SETUP.md.
)

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
