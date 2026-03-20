@echo off
cd /d "%~dp0"
echo.
echo  ============================================
echo   MOVING ALL SLs TO ENTRY — ZERO LOSS LOCK
echo  ============================================
echo.
python move_sl_to_entry.py
echo.
pause
