@echo off
title KDP Quality Dashboard
cd /d "%~dp0"
set OPENBLAS_NUM_THREADS=1
set OMP_NUM_THREADS=1
set PORT=8600
echo ==========================================================
echo   Kwangdong Quality Dashboard
echo ==========================================================
echo.
echo   Browser will open automatically in a few seconds:
echo       http://localhost:%PORT%
echo   (If it shows an error at first, wait a moment and refresh.)
echo.
echo   For coworkers on the same network, share:
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /R /C:"IPv4"') do (
  for /f "tokens=* delims= " %%b in ("%%a") do echo       http://%%b:%PORT%
)
echo.
echo   To STOP: close this window (or press Ctrl+C).
echo ==========================================================
start "" powershell -NoProfile -Command "Start-Sleep -Seconds 6; Start-Process 'http://localhost:%PORT%'"
python -m uvicorn dashboard_api:app --host 0.0.0.0 --port %PORT%
echo.
echo [Dashboard stopped]
pause
