"""
cross_bot_lock.py -- shared file-based lock to prevent 2 bots opening same symbol simultaneously.
All bots import this. Lock file lives at LOCK_FILE path.
Only tracks BOT-placed trades (magic number). Manual trades are ignored.
"""

import json, os, time
import MetaTrader5 as mt5
from datetime import datetime, timezone

LOCK_FILE  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cross_bot_active.json")
CLAIM_TTL  = 30   # seconds -- stale claim expires after 30s
BOT_MAGICS = {20260327, 20260318, 20260101, 20250101}  # all known bot magic numbers


def _read() -> dict:
    try:
        with open(LOCK_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _write(data: dict):
    try:
        with open(LOCK_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def _ticket_still_open(ticket: int) -> bool:
    """Check if a bot-placed ticket is still open in MT5. Returns False for manual/closed trades."""
    try:
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return False
        pos = positions[0]
        # Only count it as locked if it was placed by one of our bots
        if pos.magic in BOT_MAGICS:
            return True
        # Manual trade -- do not block bots
        return False
    except Exception:
        return False


def is_claimed(symbol: str) -> bool:
    """Returns True if a BOT has an open position on this symbol. Manual trades are ignored."""
    data = _read()
    entry = data.get(symbol)
    if not entry:
        return False

    # Stale placing claim -- release
    age = time.time() - entry.get("ts", 0)
    if age > CLAIM_TTL and entry.get("status") == "placing":
        release(symbol)
        return False

    # If status=open, verify the ticket is still actually open AND is a bot trade
    if entry.get("status") == "open":
        ticket = entry.get("ticket")
        if ticket and not _ticket_still_open(ticket):
            # Trade closed or was manual -- release lock
            release(symbol)
            return False

    return True


def claim(symbol: str, bot_name: str) -> bool:
    """
    Try to claim a symbol before placing.
    Returns True if claim succeeded (this bot can place).
    Returns False if another bot already claimed it.
    """
    data = _read()
    entry = data.get(symbol)
    if entry:
        age = time.time() - entry.get("ts", 0)
        if age <= CLAIM_TTL:
            return False
    data[symbol] = {
        "status": "placing",
        "bot": bot_name,
        "ts": time.time(),
        "time": datetime.now().strftime("%H:%M:%S")
    }
    _write(data)
    return True


def confirm(symbol: str, ticket: int, bot_name: str):
    """Call after trade placed successfully -- updates claim with actual ticket."""
    data = _read()
    data[symbol] = {
        "status": "open",
        "bot": bot_name,
        "ticket": ticket,
        "ts": time.time(),
        "time": datetime.now().strftime("%H:%M:%S")
    }
    _write(data)


def release(symbol: str):
    """Call when trade closes or placement fails -- frees the symbol."""
    data = _read()
    if symbol in data:
        del data[symbol]
        _write(data)


def release_all():
    """Clear all locks -- call at midnight reset."""
    _write({})
