"""
cross_bot_lock.py — shared file-based lock to prevent 2 bots opening same symbol simultaneously.
All 3 bots import this. Lock file lives at LOCK_FILE path.
"""

import json, os, time
from datetime import datetime, timezone

LOCK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cross_bot_active.json")
CLAIM_TTL = 30  # seconds — if a bot claimed a symbol but didn't place within 30s, release it


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


def is_claimed(symbol: str) -> bool:
    """Returns True if another bot has already claimed or placed this symbol recently."""
    data = _read()
    entry = data.get(symbol)
    if not entry:
        return False
    age = time.time() - entry.get("ts", 0)
    if age > CLAIM_TTL and entry.get("status") == "placing":
        # Stale claim — release it
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
            return False  # Already claimed by another bot
    # Claim it
    data[symbol] = {
        "status": "placing",
        "bot": bot_name,
        "ts": time.time(),
        "time": datetime.now().strftime("%H:%M:%S")
    }
    _write(data)
    return True


def confirm(symbol: str, ticket: int, bot_name: str):
    """Call after trade is placed successfully — updates claim with actual ticket."""
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
    """Call when trade closes or placement fails — frees the symbol."""
    data = _read()
    if symbol in data:
        del data[symbol]
        _write(data)


def release_all():
    """Clear all locks — call at midnight reset."""
    _write({})
