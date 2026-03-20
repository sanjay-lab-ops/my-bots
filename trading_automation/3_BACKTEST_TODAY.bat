@echo off
echo ============================================
echo   STEP 3 - BACKTEST TODAY
echo ============================================
echo.
echo To change date: open backtest_today.py
echo   BACKTEST_DAYS_AGO = 0  (today)
echo   BACKTEST_DAYS_AGO = 1  (yesterday)
echo   BACKTEST_DAYS_AGO = 2  (2 days ago)
echo.
python backtest_today.py
pause
