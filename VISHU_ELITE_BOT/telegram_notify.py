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

BOT_LABEL = "⚡ <b>[BOT 2 — ELITE]</b>"


def _send(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return  # silently skip if not configured
    try:
        url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": f"{BOT_LABEL}\n{message}", "parse_mode": "HTML"}
        requests.post(url, data=data, timeout=5)
    except Exception as e:
        logger.warning("Telegram send failed: %s", e)


def notify_trade_opened(symbol, action, lot, entry, sl, tp, ticket=None):
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
    if ticket:
        msg += f"\nTicket : #{ticket}"
    _send(msg)


def notify_trade_closed(symbol, action, entry, close_price, profit, reason=None):
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
        f"  BTC/ETH  → 9:00 AM–11:30 AM &amp; 5:30 PM–9:30 PM\n"
        f"  Gold/Silver → 10:30 AM–9:30 PM (continuous)\n"
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


def notify_signal(symbol, action, entry, sl, tp, rr, reason="", manual_mode=False):
    """
    Bot 2 signal alert.
    manual_mode=True  → bot did NOT execute — user must enter via opinion bot.
    manual_mode=False → bot auto-executed — alert is FYI.
    """
    emoji  = "🟢" if action.upper() == "BUY" else "🔴"
    header = "🤖 <b>[BOT 2 SIGNAL — Triple TF]</b>" if manual_mode else "📡 <b>[BOT 2 SIGNAL — Triple TF]</b>"
    copy_cmd = "{} {} {:.2f} {:.2f} auto".format(action.upper(), symbol.replace("m",""), entry, sl)
    footer = "\n⏳ <b>MANUAL MODE</b> — bot did NOT enter.\n👇 Send to opinion bot:\n<code>{}</code>".format(copy_cmd) \
        if manual_mode else \
        "\n📋 <b>Use on live?</b> Send to opinion bot:\n<code>{}</code>".format(copy_cmd)
    msg = (
        f"{header}\n"
        f"{emoji} {action.upper()} {symbol}\n"
        f"Entry  : {entry:.2f}\n"
        f"SL     : {sl:.2f}\n"
        f"TP     : {tp:.2f}\n"
        f"RR     : 1:{rr:.1f}\n"
        f"Time   : {datetime.now().strftime('%H:%M IST')}"
    )
    if reason:
        msg += f"\nReason : {reason}"
    msg += footer
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


def notify_daily_loss_limit(day_pnl: float, balance: float):
    msg = (
        f"🛑 <b>DAILY LOSS LIMIT HIT</b>\n"
        f"P&L Today : {day_pnl:+.2f} USD\n"
        f"Balance   : ${balance:.2f}\n"
        f"No new trades will be placed today.\n"
        f"Bot resumes tomorrow at midnight UTC."
    )
    _send(msg)


def notify_reconnect(attempt: int):
    msg = f"🔄 <b>MT5 RECONNECTING</b>\nAttempt #{attempt} — lost connection, trying to reconnect..."
    _send(msg)


def notify_reconnect_failed():
    msg = "❗ <b>MT5 RECONNECT FAILED</b>\nCould not reconnect to MT5. Skipping this tick.\nCheck MT5 terminal is open."
    _send(msg)


def notify_daily_summary(day_pnl: float, wins: int, losses: int, balance: float, next_event: str = ""):
    emoji = "🏆" if day_pnl >= 0 else "📊"
    msg = (
        f"{emoji} <b>DAILY SUMMARY</b>\n"
        f"Date    : {datetime.now().strftime('%d %b %Y')}\n"
        f"P&L     : {day_pnl:+.2f} USD\n"
        f"Wins    : {wins}   Losses: {losses}\n"
        f"Balance : ${balance:.2f}"
    )
    if next_event:
        msg += f"\nNext Event: {next_event}"
    _send(msg)


def notify_account_protection(balance: float, peak: float):
    msg = (f"🚨 <b>ACCOUNT PROTECTION TRIGGERED</b>\n"
           f"Balance dropped 30% from daily peak\n"
           f"Peak: ${peak:.2f} → Now: ${balance:.2f}\n"
           f"<b>ALL NEW TRADES STOPPED for today.</b>\n"
           f"Existing positions still managed by trailing stop.")
    _send(msg)


def notify_capital_sl_to_entry(balance: float, start: float, moved: int):
    msg = (f"🔒 <b>30% CAPITAL PROFIT — SL LOCKED</b>\n"
           f"Balance ${balance:.2f} (+{((balance-start)/start*100):.0f}% on capital)\n"
           f"Moved {moved} position SLs to entry.\n"
           f"<b>Floor = $0 loss. Ceiling = full TP.</b>")
    _send(msg)


def notify_profit_trail_close(locked: float, positions: int, peak: float, current: float):
    """Sent when profit trail triggers — floating dropped 30% from peak, all closed."""
    msg = (
        f"💰 <b>PROFIT TRAIL — CLOSED ALL</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Peak floating  : <b>${peak:.2f}</b>\n"
        f"Dropped to     : ${current:.2f}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Locked profit : <b>${locked:.2f}</b>\n"
        f"Positions closed: {positions}\n\n"
        f"Intelligent exit — took best available profit before reversal."
    )
    _send(msg)


def notify_sl_to_entry_alert(floating: float, balance: float, equity: float, pct: float,
                              auto_executed: bool = False, moved: int = 0):
    """
    Alert user to run MOVE_SL_TO_ENTRY.bat — floor profit at zero loss.
    Called automatically when floating profit crosses threshold.
    """
    if auto_executed:
        msg = (
            f"🤖 <b>AUTO SL→ENTRY EXECUTED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Floating profit : <b>+${floating:.2f}</b>\n"
            f"Profit vs balance: <b>{pct:.0f}%</b>\n"
            f"Positions locked : <b>{moved}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ All SLs moved to entry automatically\n"
            f"  Worst case = <b>$0 loss</b>\n"
            f"  Best case  = <b>full TP profit intact</b>\n\n"
            f"No action needed from you."
        )
        _send(msg)
        return

    if pct >= 300:
        urgency = "🔴 MAXIMUM PROFIT ALERT"
        action  = "Run NOW — don't wait"
    elif pct >= 150:
        urgency = "🟠 HIGH PROFIT ALERT"
        action  = "Strong signal to lock floor"
    else:
        urgency = "🟡 PROFIT LOCK ALERT"
        action  = "Good time to lock floor"

    msg = (
        f"⏰ <b>MOVE SL TO ENTRY — {urgency}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Floating profit : <b>+${floating:.2f}</b>\n"
        f"Balance         : ${balance:.2f}\n"
        f"Equity          : ${equity:.2f}\n"
        f"Profit vs balance: <b>{pct:.0f}%</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 {action}\n\n"
        f"▶️ Run on your PC:\n"
        f"<code>MOVE_SL_TO_ENTRY.bat</code>\n\n"
        f"✅ After running:\n"
        f"  Worst case = <b>$0 loss</b>\n"
        f"  Best case  = <b>full TP profit intact</b>"
    )
    _send(msg)
