@echo off
chcp 65001 > nul
title FunPay Parser ^& Market Intelligence Engine
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [FunPay Analytics] Creating isolated virtual environment .venv...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment!
        pause
        exit /b 1
    )
)

"%~dp0.venv\Scripts\python.exe" -c "import curl_cffi, rich, loguru" >nul 2>&1
if errorlevel 1 (
    echo [FunPay Analytics] Installing dependencies from requirements.txt...
    call "%~dp0.venv\Scripts\python.exe" -m pip install --upgrade pip -q
    if errorlevel 1 (
        echo [WARNING] Failed to upgrade pip, continuing with dependencies...
    )
    call "%~dp0.venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies from requirements.txt!
        pause
        exit /b 1
    )
    echo [OK] Virtual environment prepared successfully!
)

set "PYTHON_CMD=%~dp0.venv\Scripts\python.exe"
"%PYTHON_CMD%" -u main.py
set "EXIT_CODE=%ERRORLEVEL%"
pause
exit /b %EXIT_CODE%
