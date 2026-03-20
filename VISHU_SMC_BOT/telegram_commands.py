"""
Telegram Command Listener — Bot 3 SMC
Runs in a background thread, polls for incoming Telegram commands.

Commands:
  /setbias SYMBOL DIRECTION  → override bot direction for a symbol
      Examples: /setbias BTCUSD buy
                /setbias XAUUSD sell
                /setbias ETHUSD auto   (removes override, bot decides)
  /bias                      → show current forced biases
  /clearbias                 → reset all overrides to auto

FORCED_BIAS is stored in forced_bias.json — main loop reads it each scan.
No restart needed. Takes effect within 60 seconds.
"""

import os
import json
import time
import logging
import threading
import requests

logger = logging.getLogger("tg_commands")

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

_BIAS_FILE   = os.path.join(os.path.dirname(__file__), "forced_bias.json")
_STATE_FILE  = os.path.join(os.path.dirname(__file__), "bot_state.json")

def is_paused() -> bool:
    try:
        if os.path.exists(_STATE_FILE):
            return json.load(open(_STATE_FILE)).get("paused", False)
    except Exception:
        pass
    return False

def _set_paused(val: bool):
    with open(_STATE_FILE, "w") as f:
        json.dump({"paused": val}, f)
_VALID_SYMBOLS    = {"BTCUSD", "ETHUSD", "XAUUSD", "XAGUSD"}
_VALID_DIRECTIONS = {"buy", "sell", "auto"}

BOT_LABEL = "🏦 <b>[BOT 3 — SMC]</b>"


def _send(msg: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": f"{BOT_LABEL}\n{msg}", "parse_mode": "HTML"},
            timeout=5,
        )
    except Exception as e:
        logger.warning("Telegram send failed: %s", e)


def load_forced_bias() -> dict:
    """Load forced_bias.json. Returns dict like {'BTCUSD': 'auto', ...}"""
    defaults = {s: "auto" for s in _VALID_SYMBOLS}
    if not os.path.exists(_BIAS_FILE):
        return defaults
    try:
        with open(_BIAS_FILE) as f:
            data = json.load(f)
        for sym in _VALID_SYMBOLS:
            if sym not in data:
                data[sym] = "auto"
        return data
    except Exception:
        return defaults


def _save_forced_bias(data: dict):
    with open(_BIAS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _mt5_status() -> str:
    try:
        import MetaTrader5 as mt5
        info = mt5.account_info()
        positions = mt5.positions_get() or []
        lines = [f"💰 <b>Balance:</b> ${info.balance:.2f} | Equity: ${info.equity:.2f}"]
        if positions:
            lines.append(f"\n📂 <b>Open Positions ({len(positions)}):</b>")
            for p in positions:
                direction = "BUY" if p.type == 0 else "SELL"
                icon = "🟢" if p.profit >= 0 else "🔴"
                lines.append(f"{icon} {p.symbol} {direction} @ {p.price_open:.2f} | P&L: ${p.profit:.2f} | Ticket: {p.ticket}")
        else:
            lines.append("\n📂 No open positions")
        orders = mt5.orders_get() or []
        if orders:
            lines.append(f"\n⏳ <b>Pending Orders ({len(orders)}):</b>")
            for o in orders:
                otype = "BUY LMT" if o.type == 2 else "SELL LMT"
                lines.append(f"⏳ {o.symbol} {otype} @ {o.price_open:.2f} | Ticket: {o.ticket}")
        return "\n".join(lines)
    except Exception as e:
        return f"MT5 error: {e}"


def _handle_command(text: str):
    parts = text.strip().split()
    cmd = parts[0].lower()

    if cmd in ("/status", "/balance", "/positions"):
        _send(_mt5_status())
        return

    if cmd == "/close":
        if len(parts) != 2 or not parts[1].isdigit():
            _send("Usage: <code>/close TICKET</code>\nExample: <code>/close 2055657403</code>")
            return
        try:
            import MetaTrader5 as mt5
            ticket = int(parts[1])
            positions = mt5.positions_get() or []
            pos = next((p for p in positions if p.ticket == ticket), None)
            if not pos:
                _send(f"Ticket {ticket} not found.")
                return
            close_type = mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY
            tick = mt5.symbol_info_tick(pos.symbol)
            price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask
            req = {
                "action": mt5.TRADE_ACTION_DEAL, "symbol": pos.symbol,
                "volume": pos.volume, "type": close_type,
                "position": ticket, "price": price, "deviation": 20,
                "magic": pos.magic, "comment": "TG-close",
                "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(req)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                _send(f"✅ Ticket {ticket} closed.")
            else:
                _send(f"❌ Close failed: {result.comment if result else 'unknown'}")
        except Exception as e:
            _send(f"Error: {e}")
        return

    if cmd == "/setbias":
        if len(parts) != 3:
            _send("Usage: <code>/setbias SYMBOL DIRECTION</code>\nExample: <code>/setbias BTCUSD buy</code>")
            return
        symbol    = parts[1].upper()
        direction = parts[2].lower()
        if symbol not in _VALID_SYMBOLS:
            _send(f"Unknown symbol: {symbol}\nValid: {', '.join(_VALID_SYMBOLS)}")
            return
        if direction not in _VALID_DIRECTIONS:
            _send(f"Invalid direction: {direction}\nValid: buy | sell | auto")
            return
        bias = load_forced_bias()
        bias[symbol] = direction
        _save_forced_bias(bias)
        icon = "🟢" if direction == "buy" else "🔴" if direction == "sell" else "⚪"
        _send(f"{icon} <b>Forced bias set</b>\n{symbol}: <b>{direction.upper()}</b>\nTakes effect within 60s.")
        logger.info("FORCED_BIAS updated: %s → %s", symbol, direction)

    elif cmd == "/bias":
        bias = load_forced_bias()
        lines = []
        for sym in ["BTCUSD", "ETHUSD", "XAUUSD", "XAGUSD"]:
            d = bias.get(sym, "auto")
            icon = "🟢" if d == "buy" else "🔴" if d == "sell" else "⚪"
            lines.append(f"{icon} {sym}: <b>{d.upper()}</b>")
        _send("📊 <b>Current Forced Biases</b>\n" + "\n".join(lines))

    elif cmd == "/clearbias":
        bias = {s: "auto" for s in _VALID_SYMBOLS}
        _save_forced_bias(bias)
        _send("⚪ All forced biases cleared — bot using auto analysis.")
        logger.info("FORCED_BIAS cleared — all auto")

    elif cmd == "/pause":
        _set_paused(True)
        _send("⏸ <b>Bot PAUSED</b> — no new trades will open.\nOpen positions still managed.\nSend /resume to restart.")
        logger.info("Bot paused via Telegram.")

    elif cmd == "/resume":
        _set_paused(False)
        _send("▶️ <b>Bot RESUMED</b> — scanning for new trades again.")
        logger.info("Bot resumed via Telegram.")

    elif cmd == "/help":
        _send(
            "📋 <b>Available Commands</b>\n\n"
            "📊 <b>Account</b>\n"
            "/status — open positions + P&L\n"
            "/balance — balance & equity\n"
            "/positions — same as /status\n\n"
            "🔧 <b>Trade Control</b>\n"
            "/pause — stop new trades (manages existing)\n"
            "/resume — start scanning again\n"
            "/close TICKET — close a position\n"
            "  e.g. <code>/close 2055657403</code>\n\n"
            "🎯 <b>Bias Override</b>\n"
            "/setbias SYMBOL DIR — force direction\n"
            "  e.g. <code>/setbias BTCUSD buy</code>\n"
            "/bias — show current overrides\n"
            "/clearbias — reset all to auto"
        )


def _poll_loop():
    """Background thread: polls Telegram getUpdates for commands."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured — command polling disabled.")
        return

    offset = 0
    logger.info("Telegram command listener started.")

    while True:
        try:
            resp = requests.get(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
                params={"offset": offset, "timeout": 10, "allowed_updates": ["message"]},
                timeout=15,
            )
            updates = resp.json().get("result", [])
            for update in updates:
                offset = update["update_id"] + 1
                msg  = update.get("message", {})
                text = msg.get("text", "").strip()
                chat = str(msg.get("chat", {}).get("id", ""))
                if chat != str(TELEGRAM_CHAT_ID):
                    continue
                if text.startswith("/"):
                    logger.info("Received command: %s", text)
                    _handle_command(text)
        except Exception as e:
            logger.debug("Poll error: %s", e)
            time.sleep(5)


def start():
    """Start the background Telegram command listener thread."""
    t = threading.Thread(target=_poll_loop, daemon=True, name="tg-commands")
    t.start()
    logger.info("Telegram command listener thread started.")
