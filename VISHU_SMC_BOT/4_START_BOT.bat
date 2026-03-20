@echo off
echo ============================================
echo   VISHU SMC BOT - START (LIVE/DEMO)
echo ============================================
echo.
echo Make sure MT5 is open and logged in!
echo Bot runs 24/7 - scans BTC, ETH, XAU, XAG
echo Institutional order block execution
echo Compounding 1.5%% per trade
echo.
echo Press Ctrl+C to stop the bot safely.
echo.
pause
cd /d "%~dp0"
python main.py
pause
