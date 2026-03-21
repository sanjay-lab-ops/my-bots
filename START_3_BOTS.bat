@echo off
title VISHU TRADING SYSTEM
color 0A
echo.
echo  =====================================================
echo   VISHU TRADING SYSTEM --- 3 BOTS
echo  =====================================================
echo.
echo   BOT 1  : UTBot + VWAP + EMA     : Session-based
echo   BOT 2  : Triple TF Confluence   : Session-based
echo   BOT 3  : SMC Order Blocks/FVG   : 24/7
echo.
echo   All bots execute trades independently.
echo   Magic: Bot1=20260318  Bot2=20260319  Bot3=20260320
echo.
echo  =====================================================
echo   Make sure MetaTrader 5 is open and logged in!
echo  =====================================================
echo.
pause

echo.
echo  [1/3] Starting Bot 1 - UTBot + VWAP...
start "BOT 1 - UTBot+VWAP" cmd /k "cd /d C:\BAS_AUTOMATION\my-bots\trading_automation && python main.py"
timeout /t 4 /nobreak >nul

echo  [2/3] Starting Bot 2 - Triple TF...
start "BOT 2 - Triple TF" cmd /k "cd /d C:\BAS_AUTOMATION\my-bots\VISHU_ELITE_BOT && python main.py"
timeout /t 4 /nobreak >nul

echo  [3/3] Starting Bot 3 - SMC 24/7...
start "BOT 3 - SMC 24/7" cmd /k "cd /d C:\BAS_AUTOMATION\my-bots\VISHU_SMC_BOT && python main.py"

echo.
echo  =====================================================
echo   ALL 3 BOTS LAUNCHED
echo.
echo   SESSION WINDOWS (IST)
echo   ---------------------------------------------------
echo   Bot 1  BTC/ETH     : 09:00-11:30  17:30-21:30
echo   Bot 1  Gold/Silver : 10:30-14:00  19:00-21:30
echo   Bot 2  BTC/ETH     : 07:30-09:30  14:30-17:00  19:00-21:30
echo   Bot 2  Gold/Silver : 10:30-14:00  19:00-21:30
echo   Bot 3  All pairs   : 24/7 - H4 closes at 01:30 05:30 09:30 13:30 17:30 21:30
echo.
echo   Telegram commands:
echo   /setbias BTCUSD buy   -- force direction
echo   /bias                 -- show current overrides
echo   /clearbias            -- reset to auto
echo.
echo   You can close this window.
echo  =====================================================
echo.
pause
