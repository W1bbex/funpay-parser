@echo off
chcp 65001 > nul
title FunPay Analytics & Market Intelligence Engine
cd /d "%~dp0"
python main.py
pause
