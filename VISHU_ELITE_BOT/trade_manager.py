"""
VISHU ELITE BOT — Trade Manager
Monitors all open bot trades and applies trailing stop and breakeven logic.

Checks every TRADE_MANAGER_INTERVAL seconds (default 30s):

  Breakeven rule:
    When profit >= 1× SL distance → move SL to entry price (zero-loss guarantee)

  Trailing stop rule:
    When profit > 1.5× SL distance → trail SL at 1× ATR below price (BUY)
                                       or 1× ATR above price (SELL)

  Session close rule:
    If session window ends and trade is still open with profit > 0 → close it
"""

import logging
import MetaTrader5 as mt5

from config import (
    SYMBOLS, ATR_PERIOD, ATR_SL_MULT, MAGIC_NUMBER,
    BREAKEVEN_ATR_MULT, TRAIL_ATR_MULT, TRAIL_DISTANCE_MULT,
)
from executor import modify_sl, close_trade
from mt5_conn import get_candles, get_current_price, get_bot_positions
from indicators import get_atr_value
from session import is_session_active, get_ist_time_label
import telegram_notify as tg

# ── Closed position tracker ───────────────────────────────────────────────────
_tracked: dict = {}   # {ticket: {symbol, type, entry, sl, tp}}


def _snapshot(symbol: str, positions: list):
    for pos in positions:
        _tracked[pos.ticket] = {
            "symbol": symbol, "type": pos.type,
            "entry": pos.price_open, "sl": pos.sl, "tp": pos.tp,
        }


def detect_closed_positions(current_tickets: set):
    """Detect SL/TP hits — tickets that disappeared from open positions."""
    for ticket in set(_tracked.keys()) - current_tickets:
        info      = _tracked.pop(ticket)
        symbol    = info["symbol"]
        direction = "BUY" if info["type"] == mt5.ORDER_TYPE_BUY else "SELL"
        close_price, profit, reason = 0.0, 0.0, "Closed"
        try:
            deals = [d for d in (mt5.history_deals_get(position=ticket) or [])
                     if d.entry == mt5.DEAL_ENTRY_OUT]
            if deals:
                d = max(deals, key=lambda x: x.time)
                close_price, profit = d.price, d.profit
                tol = abs(info["tp"] - info["entry"]) * 0.05
                if abs(close_price - info["sl"]) < tol:   reason = "🛑 SL HIT"
                elif abs(close_price - info["tp"]) < tol: reason = "✅ TP HIT"
                else:                                      reason = "Manual / other"
        except Exception as e:
            logger.warning("History fetch failed ticket=%d: %s", ticket, e)
        logger.info("CLOSED | %s %s | Entry=%.2f Close=%.2f P&L=%.2f | %s",
                    direction, symbol, info["entry"], close_price, profit, reason)
        try:
            tg.notify_trade_closed(symbol, direction, info["entry"], close_price, profit, reason=reason)
        except Exception as e:
            logger.warning("TG close notify failed: %s", e)

logger = logging.getLogger("trade_manager")


def _get_atr_for_symbol(symbol: str) -> float:
    """Fetch 4H ATR for a symbol. Returns 0.0 on failure."""
    mt5_sym = SYMBOLS.get(symbol, {}).get("mt5_symbol", symbol)
    df_4h   = get_candles(mt5_sym, "H4", ATR_PERIOD + 10)
    if df_4h.empty:
        return 0.0
    return get_atr_value(df_4h, ATR_PERIOD)


def _sl_distance(position) -> float:
    """Return the original SL distance in price points for a position."""
    return abs(position.price_open - position.sl)


def check_breakeven(position, atr_val: float, symbol: str) -> bool:
    """
    Apply breakeven: if profit >= 1× SL distance, move SL to entry.
    Returns True if SL was modified.
    """
    sl_dist = _sl_distance(position)
    if sl_dist <= 0:
        return False

    # Current unrealized profit in price points
    if position.type == mt5.ORDER_TYPE_BUY:
        profit_pts = position.price_current - position.price_open
        new_sl     = position.price_open     # move to entry
        # Only apply if SL is still below entry (not already at breakeven or better)
        already_be = position.sl >= position.price_open
    else:
        profit_pts = position.price_open - position.price_current
        new_sl     = position.price_open
        already_be = position.sl <= position.price_open

    if already_be:
        return False

    breakeven_trigger = sl_dist * BREAKEVEN_ATR_MULT   # 1× SL distance

    if profit_pts >= breakeven_trigger:
        decimals = 2 if "XAU" in symbol else 1
        new_sl_r = round(new_sl, decimals)

        logger.info(
            "BREAKEVEN triggered | Ticket=%d | %s | profit_pts=%.2f >= trigger=%.2f | "
            "Moving SL from %.5f to entry %.5f",
            position.ticket, symbol, profit_pts, breakeven_trigger,
            position.sl, new_sl_r,
        )

        if modify_sl(position.ticket, symbol, new_sl_r):
            tg.notify_breakeven(symbol, position.ticket, position.price_open, new_sl_r)
            return True

    return False


def check_trailing_stop(position, atr_val: float, symbol: str) -> bool:
    """
    Trail only near TP — hold full position until within 0.5× ATR of target.
    Returns True if SL was modified.
    """
    if atr_val <= 0 or position.tp == 0:
        return False

    trail_gap = atr_val * 0.3   # tight trail near finish line
    decimals  = 2 if "XAU" in symbol else 1

    if position.type == mt5.ORDER_TYPE_BUY:
        dist_to_tp = position.tp - position.price_current
        if dist_to_tp > atr_val * 0.5:
            return False   # not near TP yet — hold full position
        new_sl = round(position.price_current - trail_gap, decimals)
        # Only move SL up, never down
        if new_sl <= position.sl:
            return False
    else:  # SELL
        dist_to_tp = position.price_current - position.tp
        if dist_to_tp > atr_val * 0.5:
            return False   # not near TP yet — hold full position
        new_sl = round(position.price_current + trail_gap, decimals)
        if new_sl >= position.sl:
            return False

    logger.info(
        "NEAR-TP TRAIL | Ticket=%d | %s | Moving SL from %.5f to %.5f",
        position.ticket, symbol, position.sl, new_sl,
    )

    if modify_sl(position.ticket, symbol, new_sl):
        tg.notify_trailing_stop(symbol, position.ticket, new_sl)
        return True

    return False


def check_session_close(position, symbol: str) -> bool:
    """
    Close trade if session has ended AND trade is in profit.
    Returns True if trade was closed.
    """
    if is_session_active(symbol):
        return False   # still in session, do not close

    # Session is over — close if profitable
    if position.profit > 0:
        logger.info(
            "SESSION END CLOSE | Ticket=%d | %s | Profit=+%.2f — closing profitable trade",
            position.ticket, symbol, position.profit,
        )
        if close_trade(position.ticket, symbol):
            _tracked.pop(position.ticket, None)  # prevent detect_closed_positions from re-notifying
            tg.notify_trade_closed(
                symbol,
                "BUY" if position.type == mt5.ORDER_TYPE_BUY else "SELL",
                position.price_open,
                position.price_current,
                position.profit,
                reason="Session ended — locking profit",
            )
            return True

    return False


def run_trade_manager() -> dict:
    """
    Main entry point: check all open bot positions and apply rules.

    Called every TRADE_MANAGER_INTERVAL seconds from main loop.

    Returns summary dict:
        {
            "checked":   int,   # positions checked
            "breakeven": int,   # breakeven SL moves
            "trailing":  int,   # trailing SL moves
            "closed":    int,   # positions closed
        }
    """
    summary = {"checked": 0, "breakeven": 0, "trailing": 0, "closed": 0}

    # ── Detect SL/TP hits from previous tick ────────────────────────────────
    all_current_tickets: set = set()
    for symbol in SYMBOLS:
        mt5_sym = SYMBOLS[symbol]["mt5_symbol"]
        for pos in (get_bot_positions(mt5_sym) or []):
            all_current_tickets.add(pos.ticket)
    detect_closed_positions(all_current_tickets)

    for symbol in SYMBOLS:
        mt5_sym   = SYMBOLS[symbol]["mt5_symbol"]
        positions = get_bot_positions(mt5_sym)

        if not positions:
            continue

        _snapshot(symbol, positions)   # update tracker for next tick

        # Fetch ATR once per symbol (4H timeframe)
        atr_val = _get_atr_for_symbol(symbol)

        for pos in positions:
            summary["checked"] += 1

            # Session close DISABLED — let SL/TP and trail stop manage exits.
            # Closing at session end with small profit misses trend continuation.

            # 1. Breakeven check
            if check_breakeven(pos, atr_val, symbol):
                summary["breakeven"] += 1
                # Re-fetch position to get updated SL before trailing check
                refreshed = mt5.positions_get(symbol=mt5_sym)
                if refreshed:
                    for rp in refreshed:
                        if rp.ticket == pos.ticket:
                            pos = rp
                            break

            # 3. Trailing stop check
            if check_trailing_stop(pos, atr_val, symbol):
                summary["trailing"] += 1

    if summary["checked"] > 0:
        logger.info(
            "Trade manager run | %s | checked=%d, breakeven=%d, trailing=%d, closed=%d",
            get_ist_time_label(),
            summary["checked"], summary["breakeven"],
            summary["trailing"], summary["closed"],
        )

    return summary
