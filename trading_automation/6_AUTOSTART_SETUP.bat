@echo off
echo ============================================
echo   STEP 6 - AUTO START SETUP (Run once only)
echo   RIGHT-CLICK and RUN AS ADMINISTRATOR
echo ============================================
echo.
set FOLDER=%~dp0

echo --- AUTO BOT (trades automatically) ---
schtasks /create /tn "VishuBot_BTC_Morning"  /tr "cmd /k \"%FOLDER%autostart_runner.bat\"" /sc daily /st 09:15 /f
echo [OK] Auto Bot - BTC Morning  9:15 AM IST

schtasks /create /tn "VishuBot_Gold_Morning" /tr "cmd /k \"%FOLDER%autostart_runner.bat\"" /sc daily /st 11:15 /f
echo [OK] Auto Bot - Gold Morning 11:15 AM IST

schtasks /create /tn "VishuBot_BTC_Evening"  /tr "cmd /k \"%FOLDER%autostart_runner.bat\"" /sc daily /st 17:15 /f
echo [OK] Auto Bot - BTC Evening  5:15 PM IST

schtasks /create /tn "VishuBot_Gold_Evening" /tr "cmd /k \"%FOLDER%autostart_runner.bat\"" /sc daily /st 19:15 /f
echo [OK] Auto Bot - Gold Evening 7:15 PM IST

echo.
echo --- MANUAL ASSISTANT (Telegram alerts only) ---
schtasks /create /tn "VishuManual_BTC_Morning"  /tr "cmd /k \"%FOLDER%manual_runner.bat\"" /sc daily /st 09:10 /f
echo [OK] Manual Alert - BTC Morning  9:10 AM IST (5 min early)

schtasks /create /tn "VishuManual_Gold_Morning" /tr "cmd /k \"%FOLDER%manual_runner.bat\"" /sc daily /st 11:10 /f
echo [OK] Manual Alert - Gold Morning 11:10 AM IST (5 min early)

schtasks /create /tn "VishuManual_BTC_Evening"  /tr "cmd /k \"%FOLDER%manual_runner.bat\"" /sc daily /st 17:10 /f
echo [OK] Manual Alert - BTC Evening  5:10 PM IST (5 min early)

schtasks /create /tn "VishuManual_Gold_Evening" /tr "cmd /k \"%FOLDER%manual_runner.bat\"" /sc daily /st 19:10 /f
echo [OK] Manual Alert - Gold Evening 7:10 PM IST (5 min early)

echo.
echo ============================================
echo   Done! Both bots will auto-start every day.
echo.
echo   AUTO BOT    - starts 15 min before session
echo   MANUAL ALERT- starts 20 min before session
echo                 (gives you time to prepare)
echo.
echo   PC must be ON during session times.
echo ============================================
pause
