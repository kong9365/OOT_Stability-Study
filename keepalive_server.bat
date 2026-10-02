@echo off
title KDP Dashboard KeepAlive (auto-restart)
cd /d "%~dp0"
set OPENBLAS_NUM_THREADS=1
set OMP_NUM_THREADS=1
set KDP_CACHE_TTL_SEC=21600
set KDP_WARM_CODES=10024,29228,23260,23262,23263,23149,23150
set PORT=8502
:loop
echo [%date% %time%] starting uvicorn on :%PORT% >> "%~dp0_keepalive.log"
python -m uvicorn dashboard_api:app --host 0.0.0.0 --port %PORT% >> "%~dp0_keepalive.log" 2>&1
echo [%date% %time%] server exited, restarting in 5s... >> "%~dp0_keepalive.log"
timeout /t 5 /nobreak >nul
goto loop
