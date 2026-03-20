"""
Day Filter — Weekly Pattern + Holiday Calendar
================================================
Blocks or reduces lot size on low-probability days.

Research-based day ratings for XAUUSD + BTCUSD:
  Monday   — Choppy, weekend gap fills, direction unclear   → SKIP
  Tuesday  — Strong institutional moves begin               → BEST
  Wednesday— Continuation + pre-Fed/data positioning        → BEST
  Thursday — Strong directional follow-through              → GOOD
  Friday   — Dangerous: profit-taking, weekend risk, stops  → HALF LOT only

Holidays: US + UK market closures (Gold + BTC most affected)
"""

from datetime import date, datetime, timezone
from typing import Tuple
from config import DEMO_MODE

# ── Day ratings ──────────────────────────────────────────────────
# (trade: bool, lot_multiplier: float, reason: str)
# Note: Saturday/Sunday XAUUSD = closed. BTCUSD = open (crypto 24/7)
DAY_CONFIG = {
    0: (False, 0.0,  "Monday  — Choppy, gap fills, low quality signals. SKIP."),
    1: (True,  1.0,  "Tuesday — Best day. Institutional moves. Full lot."),
    2: (True,  1.0,  "Wednesday — Pre-event positioning. Full lot."),
    3: (True,  1.0,  "Thursday — Strong follow-through. Full lot."),
    4: (True,  0.5,  "Friday  — Weekend risk. Half lot only."),
    5: (True,  0.5,  "Saturday — BTC only (crypto 24/7). Half lot. Gold closed."),
    6: (True,  0.5,  "Sunday  — BTC only (crypto 24/7). Half lot. Gold closed."),
}

# Days when XAUUSD is closed (weekend) — bot skips Gold on these days
XAUUSD_CLOSED_DAYS = {5, 6}   # Saturday=5, Sunday=6

# ── US + UK Market Holidays 2026 ─────────────────────────────────
# These are dates when Gold + BTC liquidity drops sharply.
# Format: (month, day, label)
MARKET_HOLIDAYS_2026 = [
    (1,  1,  "New Year's Day"),
    (1,  19, "Martin Luther King Jr. Day (US)"),
    (2,  16, "Presidents Day (US)"),
    (4,  3,  "Good Friday (US + UK)"),
    (4,  6,  "Easter Monday (UK)"),
    (5,  4,  "Early May Bank Holiday (UK)"),
    (5,  25, "Spring Bank Holiday (UK)"),
    (5,  25, "Memorial Day (US)"),
    (7,  4,  "Independence Day (US)"),
    (8,  31, "Summer Bank Holiday (UK)"),
    (9,  7,  "Labor Day (US)"),
    (11, 26, "Thanksgiving (US)"),
    (12, 25, "Christmas Day"),
    (12, 26, "Boxing Day (UK)"),
    (12, 31, "New Year's Eve — thin liquidity"),
]

# ── Indian Trading Holidays 2026 (NSE/BSE closed — user is in India) ──
INDIA_HOLIDAYS_2026 = [
    (1,  26, "Republic Day (India)"),
    (3,  20, "Holi / Eid al-Fitr"),
    (4,  14, "Dr. Ambedkar Jayanti / Good Friday"),
    (5,  1,  "Maharashtra Day / Labour Day"),
    (8,  15, "Independence Day (India)"),
    (10, 2,  "Gandhi Jayanti"),
    (10, 22, "Dussehra"),
    (11, 3,  "Diwali"),
    (11, 4,  "Diwali (Laxmi Pujan)"),
    (12, 25, "Christmas"),
]


def is_holiday(check_date: date = None) -> Tuple[bool, str]:
    """Returns (is_holiday, holiday_name)."""
    if check_date is None:
        check_date = datetime.now(timezone.utc).date()

    m, d = check_date.month, check_date.day

    for month, day, label in MARKET_HOLIDAYS_2026:
        if month == m and day == d:
            return True, label

    return False, ""


def is_india_holiday(check_date: date = None) -> Tuple[bool, str]:
    """Check Indian holidays — user may not be available to monitor."""
    if check_date is None:
        check_date = datetime.now(timezone.utc).date()
    m, d = check_date.month, check_date.day
    for month, day, label in INDIA_HOLIDAYS_2026:
        if month == m and day == d:
            return True, label
    return False, ""


def get_day_info(check_date: date = None, symbol: str = None) -> Tuple[bool, float, str]:
    """
    Returns (should_trade, lot_multiplier, reason).
    Pass symbol='XAUUSD' or 'BTCUSD' for pair-specific logic.
    Gold closed on weekends. BTC open 24/7.
    """
    if check_date is None:
        check_date = datetime.now(timezone.utc).date()

    weekday = check_date.weekday()
    tradeable, lot_mult, day_reason = DAY_CONFIG[weekday]

    # Gold is closed on weekends — skip regardless
    if symbol == "XAUUSD" and weekday in XAUUSD_CLOSED_DAYS:
        return False, 0.0, "XAUUSD closed on weekends"

    if not tradeable:
        return False, 0.0, day_reason

    # Market holiday
    holiday, holiday_name = is_holiday(check_date)
    if holiday:
        return False, 0.0, f"Market holiday: {holiday_name}"

    # Indian holiday — half lot on live (unattended), full lot on demo
    india_hol, india_name = is_india_holiday(check_date)
    if india_hol:
        if DEMO_MODE:
            return True, 1.0, f"India holiday ({india_name}) — full lot (demo mode)"
        return True, 0.5, f"India holiday ({india_name}) — half lot (unattended)"

    return tradeable, lot_mult, day_reason


def weekly_summary() -> str:
    """Print a summary of this week's trading schedule."""
    from datetime import timedelta
    today = datetime.now(timezone.utc).date()
    # Find Monday of this week
    monday = today - timedelta(days=today.weekday())

    lines = ["\n  THIS WEEK TRADING SCHEDULE", "  " + "─" * 45]
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    for i in range(7):
        d = monday + timedelta(days=i)
        tradeable, lot_mult, reason = get_day_info(d)
        status = f"✅ TRADE (lot ×{lot_mult})" if tradeable else "❌ SKIP"
        hol, hol_name = is_holiday(d)
        holiday_tag = f" [{hol_name}]" if hol else ""
        lines.append(f"  {days[i]} {d.strftime('%d %b')} | {status} | {reason[:40]}{holiday_tag}")

    lines.append("  " + "─" * 45)
    return "\n".join(lines)
