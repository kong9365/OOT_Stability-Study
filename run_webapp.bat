@echo off
title Kwangdong Quality Dashboard (Web)
cd /d "%~dp0"
set OPENBLAS_NUM_THREADS=1
set OMP_NUM_THREADS=1
REM 데이터 캐시 6시간 유지 - 처음 조회만 느리고 이후 즉시(Tableau 재조회 생략)
set KDP_CACHE_TTL_SEC=21600
REM 기동 시 미리 받아둘 품목코드(콤마구분) - 자주/크게 쓰는 품목을 넣으면 첫 조회부터 빠름
set KDP_WARM_CODES=10024,29228,23260,23262,23263,23149,23150
set PORT=8502
echo ==========================================================
echo   Kwangdong Quality Dashboard (Web / FastAPI)
echo ==========================================================
echo.
echo   Access URL:
echo     - This PC      :  http://localhost:%PORT%
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /R /C:"IPv4"') do (
  for /f "tokens=* delims= " %%b in ("%%a") do echo     - LAN/Coworker :  http://%%b:%PORT%
)
echo.
echo   * Allow TCP %PORT% inbound in Windows Firewall for coworkers.
echo   * Stop: press Ctrl+C in this window.
echo ==========================================================
echo.
python -m uvicorn dashboard_api:app --host 0.0.0.0 --port %PORT%
echo.
echo [Web dashboard stopped]
pause
