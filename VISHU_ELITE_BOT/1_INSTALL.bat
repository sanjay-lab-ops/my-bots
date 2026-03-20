@echo off
title VISHU ELITE BOT — Install Dependencies
echo.
echo =============================================
echo   VISHU ELITE BOT — INSTALLING DEPENDENCIES
echo =============================================
echo.

pip install -r requirements.txt

echo.
echo =============================================
echo   INSTALLATION COMPLETE
echo =============================================
echo.
echo Next steps:
echo   1. Fill in your .env file with MT5 credentials
echo   2. Run 2_TEST.bat to verify MT5 connection
echo   3. Run 3_BACKTEST.bat to test the strategy
echo   4. Run 4_START_BOT.bat to go live
echo.
pause
