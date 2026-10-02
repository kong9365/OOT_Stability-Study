@echo off
title OOT Auto Alarm Scheduler
cd /d "%~dp0"
set OPENBLAS_NUM_THREADS=1
set OMP_NUM_THREADS=1
echo ==========================================================
echo   OOT Auto Alarm Scheduler - Kwangdong QC
echo ==========================================================
echo.
echo   * Schedule from oot_alert_config.json (schedule: default daily 07:30).
echo   * Override examples:  python oot_alarm.py --daily 07:30    (or)    --interval 10
echo   * First run records current OOT as baseline (no email).
echo   * Recipients / SMTP: dashboard [Alarm Settings] menu.
echo   * Stop: Ctrl+C or close this window.   Log: oot_alarm.log
echo ==========================================================
echo.
python oot_alarm.py
echo.
echo [Alarm scheduler stopped]
pause
