@echo off
title VISHU SCALP BOT — LIVE $50
color 0E

echo.
echo  =====================================================
echo   VISHU SCALP BOT — LIVE ACCOUNT
echo  =====================================================
echo.

cd /d C:\Users\Sanjay_HivePro\Downloads\my-bots\my-bots\VISHU_SCALP_BOT

echo  Checking Python...
python --version
if errorlevel 1 (
    echo.
    echo  ERROR: Python not found. Install Python from python.org
    pause
    exit /b
)

echo.
echo  Installing requirements...
pip install -r requirements.txt
echo.

echo  Checking MT5...
python -c "import MetaTrader5 as mt5; print('MT5 OK')"
if errorlevel 1 (
    echo.
    echo  ERROR: MetaTrader5 package failed. Try: pip install MetaTrader5
    pause
    exit /b
)

echo.
echo  *** LIVE MONEY — Make sure MT5 is open and logged in ***
echo.
pause

echo  Starting Scalp Bot...
python main.py

echo.
echo  Bot stopped.
pause
