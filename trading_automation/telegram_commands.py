"""
Telegram Command Listener — Bot 1 (UTBot+VWAP)
Runs in a background thread, polls for incoming commands.
"""

import os, json, time, logging, threading
import requests

logger = logging.getLogger("tg_commands")

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
BOT_LABEL        = "🤖 <b>[BOT 1 — UTBot+VWAP]</b>"
_COP_FILE        = os.path.join(os.path.dirname(__file__), "close_on_profit.json")
_STATE_FILE      = os.path.join(os.path.dirname(__file__), "bot_state.json")

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
        logger.warning("TG send failed: %s", e)


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

    elif cmd == "/close":
        if len(parts) != 2 or not parts[1].isdigit():
            _send("Usage: <code>/close TICKET</code>")
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

    elif cmd == "/cop":
        # Add ticket to close-on-profit watch list
        if len(parts) != 2 or not parts[1].isdigit():
            _send("Usage: <code>/cop TICKET</code> — close when profit turns positive")
            return
        ticket = int(parts[1])
        try:
            cops = json.load(open(_COP_FILE)).get("tickets", []) if os.path.exists(_COP_FILE) else []
        except Exception:
            cops = []
        if ticket not in cops:
            cops.append(ticket)
            with open(_COP_FILE, "w") as f:
                json.dump({"tickets": cops}, f)
        _send(f"⏰ Ticket {ticket} added to close-on-profit watch list.")

    elif cmd == "/pause":
        _set_paused(True)
        _send("⏸ <b>Bot PAUSED</b> — no new trades will open.\nOpen positions still managed.\nSend /resume to restart.")

    elif cmd == "/resume":
        _set_paused(False)
        _send("▶️ <b>Bot RESUMED</b> — scanning for new trades again.")

    elif cmd == "/help":
        _send(
            "📋 <b>Available Commands</b>\n\n"
            "📊 <b>Account</b>\n"
            "/status — open positions + P&L\n"
            "/balance — balance & equity\n\n"
            "🔧 <b>Trade Control</b>\n"
            "/pause — stop new trades (manages existing)\n"
            "/resume — start scanning again\n"
            "/close TICKET — close a position\n"
            "/cop TICKET — auto-close when first profit\n"
            "  e.g. <code>/cop 2055657403</code>"
        )


def _poll_loop():
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
    t = threading.Thread(target=_poll_loop, daemon=True, name="tg-commands")
    t.start()
    logger.info("Telegram command listener thread started.")
