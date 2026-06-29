@echo off
title KDP Quality Dashboard - Setup
cd /d "%~dp0"
echo ==========================================================
echo   Kwangdong Quality Dashboard - Setup (run ONCE)
echo ==========================================================
echo.
echo Checking Python...
python --version
if errorlevel 1 (
  echo.
  echo [ERROR] Python not found.
  echo  1) Install Python 3.10+ : https://www.python.org/downloads/
  echo  2) During install, CHECK "Add Python to PATH"
  echo  3) Then run this setup.bat again
  echo.
  pause
  exit /b 1
)
echo.
echo Installing packages (takes 1-3 minutes)...
python -m pip install --upgrade pip --trusted-host pypi.org --trusted-host files.pythonhosted.org
python -m pip install -r requirements.txt --trusted-host pypi.org --trusted-host files.pythonhosted.org
echo.
if errorlevel 1 (
  echo [WARN] Some packages failed. Check network/company proxy and retry.
) else (
  echo [OK] Setup complete. Now double-click run.bat
)
echo ==========================================================
pause
