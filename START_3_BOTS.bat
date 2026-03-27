@echo off
title VISHU TRADING SYSTEM
color 0A

cd /d %~dp0

echo.
echo  =====================================================
echo   VISHU TRADING SYSTEM --- 3 BOTS
echo  =====================================================
echo.
echo   Make sure MetaTrader 5 is open and logged in!
echo.
pause

echo.
echo  [1/3] Starting Bot 1 - UTBot + VWAP...
start "BOT 1 - UTBot+VWAP" cmd /k "cd /d C:\Users\Sanjay_HivePro\Downloads\my-bots\my-bots\trading_automation && python main.py"
timeout /t 4 /nobreak >nul

echo  [2/3] Starting Bot 2 - Triple TF...
start "BOT 2 - Triple TF" cmd /k "cd /d C:\Users\Sanjay_HivePro\Downloads\my-bots\my-bots\VISHU_ELITE_BOT && python main.py"
timeout /t 4 /nobreak >nul

echo  [3/3] Starting Bot 3 - SMC 24/7...
start "BOT 3 - SMC 24/7" cmd /k "cd /d C:\Users\Sanjay_HivePro\Downloads\my-bots\my-bots\VISHU_SMC_BOT && python main.py"

echo.
echo  ALL 3 BOTS STARTED
pause
