"""
Manual Trade Alert — send your manual trade to Telegram instantly.

Usage:
  python manual_alert.py
  Then fill in the details when asked.
"""

import os
import requests
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
IST     = timedelta(hours=5, minutes=30)


def send(msg: str):
    if not TOKEN or not CHAT_ID:
        print("Telegram not configured in .env")
        return
    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"},
        timeout=5,
    )


def ist_now():
    return (datetime.now(timezone.utc) + IST).strftime("%H:%M IST")


def main():
    print("\n══════════════════════════════════")
    print("  MANUAL TRADE ALERT")
    print("══════════════════════════════════")

    pair      = input("  Pair   (BTC/XAU/XAG/ETH)  : ").strip().upper()
    direction = input("  Direction (BUY/SELL)        : ").strip().upper()
    entry     = input("  Entry price                 : ").strip()
    sl        = input("  Stop Loss                   : ").strip()
    tp        = input("  Take Profit                 : ").strip()
    lots      = input("  Lot size                    : ").strip()
    reason    = input("  Reason (optional)           : ").strip()

    emoji = "🟢" if direction == "BUY" else "🔴"
    time  = ist_now()

    msg = (
        f"👤 <b>[MANUAL TRADE]</b>\n"
        f"{emoji} <b>{direction} {pair}</b>\n"
        f"Entry  : {entry}\n"
        f"SL     : {sl}\n"
        f"TP     : {tp}\n"
        f"Lots   : {lots}\n"
        f"Time   : {time}"
    )
    if reason:
        msg += f"\nReason : {reason}"

    send(msg)
    print(f"\n  ✅ Alert sent to Telegram at {time}")
    print("══════════════════════════════════\n")


if __name__ == "__main__":
    main()
