"""
VISHU ELITE BOT — Session Manager
Tracks London + NY open session windows for BTCUSD and XAUUSD.

BTCUSD sessions (UTC):
  02:00–04:00  Asian close
  09:00–11:30  London open
  13:30–16:00  NY open

XAUUSD sessions (UTC):
  06:00–08:30  London open
  13:30–16:00  NY open / overlap

Rules:
  - Max 1 trade per pair per session window
  - Max 2 trades per pair per day (MAX_TRADES_PAIR in config)
  - Max 4 trades total per day (MAX_TRADES_DAY in config)
"""

import logging
from datetime import datetime, timezone
from config import SESSIONS

logger = logging.getLogger("session")


def _now_utc_minutes() -> int:
    """Return current UTC time as total minutes since midnight."""
    now = datetime.now(timezone.utc)
    return now.hour * 60 + now.minute


def is_session_active(symbol: str) -> bool:
    """Return True if the current UTC time falls within ANY session window for symbol."""
    total_m = _now_utc_minutes()
    for sess in SESSIONS.get(symbol, []):
        sh, sm = sess["start_utc"]
        eh, em = sess["end_utc"]
        start_m = sh * 60 + sm
        end_m   = eh * 60 + em
        if start_m <= total_m <= end_m:
            return True
    return False


def get_active_session(symbol: str) -> dict:
    """
    Return the currently active session dict for symbol, or None.
    Dict has keys: start_utc, end_utc, label
    """
    total_m = _now_utc_minutes()
    for sess in SESSIONS.get(symbol, []):
        sh, sm = sess["start_utc"]
        eh, em = sess["end_utc"]
        start_m = sh * 60 + sm
        end_m   = eh * 60 + em
        if start_m <= total_m <= end_m:
            return sess
    return None


def get_active_session_label(symbol: str) -> str:
    """Return human-readable label for the current session, or empty string."""
    sess = get_active_session(symbol)
    return sess["label"] if sess else ""


def session_ends_in_minutes(symbol: str) -> int:
    """
    Return minutes until the current session ends.
    Returns -1 if not in a session.
    """
    total_m = _now_utc_minutes()
    sess = get_active_session(symbol)
    if not sess:
        return -1
    eh, em  = sess["end_utc"]
    end_m   = eh * 60 + em
    return max(0, end_m - total_m)


def any_session_active() -> bool:
    """Return True if ANY symbol has an active session right now."""
    from config import SYMBOLS
    return any(is_session_active(sym) for sym in SYMBOLS)


def all_sessions_done_for_day() -> bool:
    """
    Return True if we are past the last session end for ALL symbols today.
    Used for auto-stop and daily summary.
    """
    now = datetime.now(timezone.utc)
    total_m = now.hour * 60 + now.minute

    from config import SYMBOLS
    for sym in SYMBOLS:
        for sess in SESSIONS.get(sym, []):
            eh, em  = sess["end_utc"]
            end_m   = eh * 60 + em
            if total_m <= end_m:
                return False   # at least one session still ahead or active
    return True


def get_session_key(symbol: str) -> str:
    """
    Return a unique key for the current session window.
    Used as a dictionary key to track 'one trade per session' rule.
    Example: 'BTCUSD_09:00-11:30'
    """
    sess = get_active_session(symbol)
    if not sess:
        return ""
    sh, sm = sess["start_utc"]
    eh, em = sess["end_utc"]
    return f"{symbol}_{sh:02d}:{sm:02d}-{eh:02d}:{em:02d}"


def get_ist_time_label() -> str:
    """Return current time formatted in IST (UTC+5:30) for display."""
    now_utc = datetime.now(timezone.utc)
    # IST = UTC + 5h 30m
    ist_hour   = (now_utc.hour + 5) % 24
    ist_minute = now_utc.minute + 30
    if ist_minute >= 60:
        ist_minute -= 60
        ist_hour   = (ist_hour + 1) % 24
    return f"{ist_hour:02d}:{ist_minute:02d} IST"


def log_session_status():
    """Log current session status for all symbols."""
    from config import SYMBOLS
    now_label = get_ist_time_label()
    for sym in SYMBOLS:
        label = get_active_session_label(sym)
        if label:
            mins_left = session_ends_in_minutes(sym)
            logger.info(
                "SESSION ACTIVE [%s]: %s | %d min remaining | %s",
                sym, label, mins_left, now_label,
            )
        else:
            logger.debug("Session inactive for %s at %s", sym, now_label)
