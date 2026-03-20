@echo off
echo ============================================
echo   STEP 2 - TEST MT5 + TELEGRAM CONNECTION
echo ============================================
echo.
echo Testing MT5...
python test_connection.py
echo.
echo Testing Telegram...
python test_telegram.py
echo.
pause
