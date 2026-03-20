"""
Telegram notification system — sends alerts to your phone for free.

Setup (one time, takes 2 minutes):
  1. Open Telegram on your phone
  2. Search for @BotFather → send /newbot → follow steps → copy the TOKEN
  3. Search for @userinfobot → send any message → copy your chat ID
  4. Paste both in your .env file:
       TELEGRAM_TOKEN=your_bot_token
       TELEGRAM_CHAT_ID=your_chat_id
"""

import os
import logging
import requests
from datetime import datetime

logger = logging.getLogger("telegram")

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

BOT_LABEL = "🏦 <b>[BOT 3 — SMC]</b>"


def _send(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return  # silently skip if not configured
    try:
        url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": f"{BOT_LABEL}\n{message}", "parse_mode": "HTML"}
        requests.post(url, data=data, timeout=5)
    except Exception as e:
        logger.warning("Telegram send failed: %s", e)


def notify_trade_opened(symbol, action, lot, entry, sl, tp):
    emoji = "🟢" if action.upper() == "BUY" else "🔴"
    msg = (
        f"{emoji} <b>TRADE OPENED</b>\n"
        f"Pair   : {symbol}\n"
        f"Action : {action.upper()}\n"
        f"Entry  : {entry:.2f}\n"
        f"SL     : {sl:.2f}\n"
        f"TP     : {tp:.2f}\n"
        f"Lot    : {lot}\n"
        f"Time   : {datetime.now().strftime('%H:%M IST')}"
    )
    _send(msg)


def notify_trade_closed(symbol, action, entry, close_price, profit):
    emoji = "✅" if profit >= 0 else "❌"
    msg = (
        f"{emoji} <b>TRADE CLOSED</b>\n"
        f"Pair   : {symbol}\n"
        f"Action : {action.upper()}\n"
        f"Entry  : {entry:.2f}\n"
        f"Close  : {close_price:.2f}\n"
        f"P&L    : {'+'if profit>=0 else ''}{profit:.2f} USD\n"
        f"Time   : {datetime.now().strftime('%H:%M IST')}"
    )
    _send(msg)


def notify_session_start(symbol, session_label, bias):
    emoji = "📈" if bias == "buy" else "📉"
    msg = (
        f"{emoji} <b>SESSION STARTING</b>\n"
        f"Pair    : {symbol}\n"
        f"Session : {session_label}\n"
        f"Bias    : {bias.upper()} ONLY\n"
        f"Bot is scanning for entry..."
    )
    _send(msg)


def notify_skipped(symbol, reason):
    msg = (
        f"⏭ <b>TRADE SKIPPED</b>\n"
        f"Pair   : {symbol}\n"
        f"Reason : {reason}"
    )
    _send(msg)


def notify_bot_started(balance, risk_mode="aggressive", session_status=None, server=""):
    from datetime import datetime
    now_ist = datetime.now().strftime("%d %b %Y  %I:%M %p IST")

    status_lines = ""
    if session_status:
        for sym, ok, reason in session_status:
            icon = "✅" if ok else "⏭"
            status_lines += f"  {icon} {sym}: {reason}\n"
    else:
        status_lines = "  ✅ BTCUSD: Active\n  ✅ XAUUSD: Active\n"

    msg = (
        f"✅ <b>VISHU BOT — CONNECTED &amp; READY</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 Started  : {now_ist}\n"
        f"💰 Balance  : ${balance:.2f}\n"
        f"⚡ Risk Mode: {risk_mode.upper()}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 Today's Pairs:\n"
        f"{status_lines}"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 Sessions (IST):\n"
        f"  SMC Bot runs 24/7 — scans every H4 candle close\n"
        f"  H4 closes: 1:30, 5:30, 9:30, 13:30, 17:30, 21:30 IST\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏳ Watching for signals... You will be alerted the moment a trade fires."
    )
    _send(msg)


def notify_daily_report(total_pnl, wins, losses, balance):
    emoji = "🏆" if total_pnl >= 0 else "📊"
    msg = (
        f"{emoji} <b>DAILY REPORT</b>\n"
        f"Date    : {datetime.now().strftime('%d %b %Y')}\n"
        f"Wins    : {wins}   Losses: {losses}\n"
        f"P&L     : {'+'if total_pnl>=0 else ''}{total_pnl:.2f} USD\n"
        f"Balance : ${balance:.2f}"
    )
    _send(msg)


def notify_news_block(symbol, reason):
    msg = (
        f"📰 <b>TRADE BLOCKED — NEWS EVENT</b>\n"
        f"Pair   : {symbol}\n"
        f"Reason : {reason}\n"
        f"Bot will resume after event window."
    )
    _send(msg)


def notify_signal(symbol, action, entry, sl, tp, rr, reason=""):
    """
    Sent when a signal is detected — whether or not bot auto-trades.
    User can use this to enter manually.
    """
    emoji = "🟢" if action.upper() == "BUY" else "🔴"
    msg = (
        f"{emoji} <b>SIGNAL DETECTED — ENTER MANUALLY</b>\n"
        f"Pair   : {symbol}\n"
        f"Action : {action.upper()}\n"
        f"Entry  : {entry:.2f}\n"
        f"SL     : {sl:.2f}\n"
        f"TP     : {tp:.2f}\n"
        f"RR     : 1:{rr:.1f}\n"
        f"Time   : {datetime.now().strftime('%H:%M IST')}"
    )
    if reason:
        msg += f"\nReason : {reason}"
    msg += "\n\n<i>Bot is also entering. You may skip if already in.</i>"
    _send(msg)


def notify_news_trade(symbol, action, lot, entry, sl, tp, reason, confidence, headline):
    emoji = "🟢📰" if action.upper() == "BUY" else "🔴📰"
    msg = (
        f"{emoji} <b>NEWS TRADE OPENED</b>\n"
        f"Pair       : {symbol}\n"
        f"Action     : {action.upper()}\n"
        f"Entry      : {entry:.2f}\n"
        f"SL         : {sl:.2f}\n"
        f"TP         : {tp:.2f}\n"
        f"Lot        : {lot}\n"
        f"Confidence : {confidence}%\n"
        f"Reason     : {reason}\n"
        f"Headline   : {headline}\n"
        f"Time       : {datetime.now().strftime('%H:%M IST')}"
    )
    _send(msg)

# Aliases for compatibility
def bot_started(balance, growth_pct=0, **kwargs): notify_bot_started(balance, **kwargs)


def daily_loss_limit(balance: float):
    msg = (
        f"🛑 <b>DAILY LOSS LIMIT HIT</b>\n"
        f"Balance   : ${balance:.2f}\n"
        f"No new trades will be placed today.\n"
        f"Bot resumes tomorrow at midnight UTC."
    )
    _send(msg)


def daily_summary(day_pnl: float, balance: float, total_pct: float = 0,
                  win_rate: float = 0, trades: int = 0):
    emoji = "🏆" if day_pnl >= 0 else "📊"
    msg = (
        f"{emoji} <b>DAILY SUMMARY</b>\n"
        f"Date      : {datetime.now().strftime('%d %b %Y')}\n"
        f"Day P&L   : {day_pnl:+.2f} USD\n"
        f"Balance   : ${balance:.2f}\n"
        f"Total gain: +{total_pct:.1f}%\n"
        f"Win rate  : {win_rate:.0f}%  ({trades} trades total)"
    )
    _send(msg)


def compound_milestone(balance: float, total_pct: float):
    msg = (
        f"🎯 <b>COMPOUND MILESTONE!</b>\n"
        f"Total growth: +{total_pct:.1f}%\n"
        f"Balance     : ${balance:.2f}\n"
        f"Lot sizes increasing with your account!"
    )
    _send(msg)


def trade_opened(symbol, action, lot, entry, sl, tp):
    notify_trade_opened(symbol, action, lot, entry, sl, tp)


def breakeven_triggered(symbol: str, entry: float):
    msg = (
        f"🔒 <b>BREAKEVEN</b>\n"
        f"Pair  : {symbol}\n"
        f"Entry : {entry:.2f}\n"
        f"SL moved to entry — trade is now risk-free."
    )
    _send(msg)


def partial_close(symbol: str, locked_profit: float):
    msg = (
        f"💰 <b>PARTIAL CLOSE</b>\n"
        f"Pair   : {symbol}\n"
        f"Locked : +${locked_profit:.2f}\n"
        f"50% closed at 1.5:1 — rest running to TP."
    )
    _send(msg)


def trade_closed(symbol: str, direction: str, entry: float,
                 close_price: float, profit: float,
                 balance: float = 0, reason: str = ""):
    emoji = "✅" if profit >= 0 else "❌"
    msg = (
        f"{emoji} <b>TRADE CLOSED</b>\n"
        f"Pair    : {symbol}\n"
        f"Action  : {direction.upper()}\n"
        f"Entry   : {entry:.2f}\n"
        f"Close   : {close_price:.2f}\n"
        f"P&amp;L : {'+'if profit>=0 else ''}{profit:.2f} USD\n"
        f"Balance : ${balance:.2f}\n"
        f"Time    : {datetime.now().strftime('%H:%M IST')}"
    )
    if reason:
        msg += f"\nReason  : {reason}"
    _send(msg)


def notify_bot_signal(symbol, direction, entry, sl, tp, lot, reason=""):
    """Bot 3 MANUAL MODE — signal detected but NOT executed. User must enter."""
    emoji = "🟢" if direction.upper() == "BUY" else "🔴"
    copy_cmd = "{} {} {:.2f} {:.2f} auto".format(direction.upper(), symbol.replace("m",""), entry, sl)
    msg = (
        f"🤖 <b>[BOT 3 SIGNAL — SMC]</b>\n"
        f"{emoji} {direction.upper()} {symbol}\n"
        f"Entry  : {entry:.2f}\n"
        f"SL     : {sl:.2f}\n"
        f"TP     : {tp:.2f}\n"
        f"Lot    : {lot}\n"
        f"Reason : {reason}\n"
        f"Time   : {datetime.now().strftime('%H:%M IST')}\n"
        f"⏳ <b>MANUAL MODE</b> — bot did NOT enter.\n"
        f"Send to opinion bot: <code>{copy_cmd}</code>"
    )
    _send(msg)


def limit_order_placed(symbol, direction, lot, entry_price, sl, tp, reason=""):
    emoji = "🟢" if direction.upper() == "BUY" else "🔴"
    msg = (
        f"{emoji} <b>LIMIT ORDER PLACED</b>\n"
        f"Pair   : {symbol}\n"
        f"Action : {direction.upper()}\n"
        f"Entry  : {entry_price:.2f}\n"
        f"SL     : {sl:.2f}\n"
        f"TP     : {tp:.2f}\n"
        f"Lot    : {lot}\n"
        f"Reason : {reason}\n"
        f"Time   : {datetime.now().strftime('%H:%M IST')}\n"
        f"<i>Waiting for price to reach limit level...</i>"
    )
    _send(msg)
