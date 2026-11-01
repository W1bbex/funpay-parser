@echo off
chcp 65001 > nul
title FunPay Parser - Seller 14273448 Results
cd /d "%~dp0"

set "PYTHON_CMD=python"
if exist ".venv\Scripts\python.exe" set "PYTHON_CMD=.venv\Scripts\python.exe"

"%PYTHON_CMD%" -u show_seller.py %*
pause
