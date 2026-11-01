@echo off
chcp 65001 > nul
title FunPay Parser ^& Market Intelligence Engine
cd /d "%~dp0"

set "PYTHON_CMD=python"
if exist ".venv\Scripts\python.exe" set "PYTHON_CMD=.venv\Scripts\python.exe"

"%PYTHON_CMD%" -c "import curl_cffi, rich, funpayparsers, loguru, bs4" >nul 2>&1
if errorlevel 1 (
    echo [FunPay Analytics] Installing dependencies from requirements.txt...
    if not exist ".venv\Scripts\python.exe" (
        python -m venv .venv
    )
    if exist ".venv\Scripts\python.exe" set "PYTHON_CMD=.venv\Scripts\python.exe"
    call "%~dp0.venv\Scripts\python.exe" -m pip install --upgrade pip -q
    call "%~dp0.venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies from requirements.txt!
        pause
        exit /b 1
    )
    echo [OK] Dependencies installed successfully!
)

"%PYTHON_CMD%" -u main.py
pause
