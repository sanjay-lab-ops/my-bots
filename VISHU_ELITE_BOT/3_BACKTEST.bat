@echo off
title VISHU ELITE BOT — Backtest
echo.
echo =============================================
echo   VISHU ELITE BOT — SINGLE-DAY BACKTEST
echo =============================================
echo.
echo To change the backtest date:
echo   Open backtest.py in a text editor
echo   Set BACKTEST_DATE = "YYYY-MM-DD"  (e.g. "2026-03-18")
echo   Leave blank ("") to backtest TODAY
echo.
echo Starting backtest...
echo (Make sure MetaTrader 5 is open and logged in)
echo.

python backtest.py

echo.
pause
