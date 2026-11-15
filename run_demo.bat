@echo off
chcp 65001 > nul
title FunPay Parser - Seller 14273448 Results
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [FunPay Analytics] Virtual environment not found. Preparing .venv...
    call run.bat
)

set "PYTHON_CMD=%~dp0.venv\Scripts\python.exe"
"%PYTHON_CMD%" -u show_seller.py %*
set "EXIT_CODE=%ERRORLEVEL%"
pause
exit /b %EXIT_CODE%
