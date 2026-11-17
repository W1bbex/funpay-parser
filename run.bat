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

"%~dp0.venv\Scripts\python.exe" -c "import curl_cffi, rich, loguru, bs4, dotenv, funpayparsers" >nul 2>&1
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
    echo [OK] Dependencies installed successfully!
)

"%~dp0.venv\Scripts\python.exe" -c "import funpay_analytics" >nul 2>&1
if errorlevel 1 (
    echo [FunPay Analytics] Installing local funpay_analytics package...
    "%~dp0.venv\Scripts\python.exe" -c "import importlib.util, setuptools; v = tuple(int(x) for x in setuptools.__version__.split('.')[:2] if x.isdigit()); raise SystemExit(0 if (v >= (70, 1) or importlib.util.find_spec('wheel')) else 1)" >nul 2>&1
    if errorlevel 1 (
        call "%~dp0.venv\Scripts\python.exe" -m pip install --no-deps -e .
    ) else (
        call "%~dp0.venv\Scripts\python.exe" -m pip install --no-deps --no-build-isolation -e .
    )
    if errorlevel 1 (
        echo [WARNING] Editable pip install failed; trying direct src registration...
        "%~dp0.venv\Scripts\python.exe" -c "import pathlib, sysconfig; src = (pathlib.Path.cwd() / 'src').resolve(); assert (src / 'funpay_analytics' / '__init__.py').is_file(); (pathlib.Path(sysconfig.get_path('purelib')) / 'funpay_analytics.pth').write_text(str(src) + '\n', encoding='utf-8')"
    )
    "%~dp0.venv\Scripts\python.exe" -c "import funpay_analytics" >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Failed to install local funpay_analytics package!
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
