@echo off
title VISHU SCALP BOT — LIVE $50
color 0E

echo.
echo  =====================================================
echo   VISHU SCALP BOT — LIVE ACCOUNT
echo   ETH + BTC | 1M Scalping | Kill Zones Only
echo  =====================================================
echo.
echo   *** LIVE MONEY — Make sure MT5 is logged into LIVE account ***
echo.
pause

cd /d C:\Users\Sanjay_HivePro\Downloads\my-bots\my-bots\VISHU_SCALP_BOT

echo  Installing requirements...
pip install -r requirements.txt -q

echo.
echo  Starting Scalp Bot...
python main.py
pause
