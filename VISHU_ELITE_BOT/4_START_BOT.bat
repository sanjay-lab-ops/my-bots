@echo off
title VISHU ELITE BOT — LIVE
echo.
echo =============================================
echo   VISHU ELITE BOT — STARTING LIVE BOT
echo =============================================
echo.
echo IMPORTANT:
echo   - Make sure MetaTrader 5 is open and logged in
echo   - Make sure .env has your credentials filled in
echo   - Bot runs until all sessions end (16:00 UTC / 21:30 IST)
echo   - Press Ctrl+C to stop early
echo.
echo All output is also saved to: elite_bot.log
echo.

python main.py

echo.
echo Bot has stopped. Check elite_bot.log for full session log.
echo.
pause
