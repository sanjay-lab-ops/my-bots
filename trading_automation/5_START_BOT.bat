@echo off
echo ============================================
echo   STEP 5 - START LIVE BOT (DEMO ACCOUNT)
echo ============================================
echo.
echo Make sure MT5 is open and logged in first!
echo Bot will scan every 60 seconds during sessions.
echo Press Ctrl+C to stop the bot.
echo.
pause
cd /d "%~dp0"
python main.py
pause
