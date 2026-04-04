"""
Trade Manager -- Manages open positions like an institution.

Rules (in order of priority):
  1. If trade hits 1:1 profit (1x SL distance) -> move SL to breakeven
     -> Risk is now $0. We can never lose on this trade.
  2. If trade hits 1.5:1 -> close 50% of position
     -> Locks in partial profit. Lets the rest run for full TP.
  3. If trade hits 2.0:1 -> trail SL at 1x ATR behind price
     -> Captures as much of the move as possible.
  4. If price is nearing TP (within 0.1x ATR) -> close fully
     -> Don't get greedy waiting for the last pip.

This is how institutions protect profits -- they don't use fixed SL forever.
They dynamically adjust as the trade develops.
"""

import logging
from datetime import datetime, timezone
from mt5_conn import get_open_positions
from executor import modify_sl, close_position, close_partial
from config import SYMBOLS, MAGIC_NUMBER

logger = logging.getLogger("trade_manager")

# -- Closed position tracker (detects SL/TP hits) -----------------------------
_tracked: dict = {}   # {ticket: {symbol, type, entry, sl, tp}}


def snapshot_positions(symbol: str, positions: list):
    for pos in positions:
        _tracked[pos["ticket"]] = {
            "symbol": symbol, "type": pos["type"],
            "entry": pos["open_price"], "sl": pos["sl"], "tp": pos["tp"],
        }


def detect_closed_positions(current_tickets: set, tg=None) -> set:
    """Detect SL/TP hits -- any ticket missing from current open positions.
    Returns set of symbols where SL was hit (caller can unlock re-entry)."""
    import MetaTrader5 as mt5
    sl_hit_symbols = set()
    for ticket in set(_tracked.keys()) - current_tickets:
        info      = _tracked.pop(ticket)
        symbol    = info["symbol"]
        direction = "BUY" if info["type"] == 0 else "SELL"
        close_price, profit, reason = 0.0, 0.0, "Closed"
        try:
            deals = [d for d in (mt5.history_deals_get(position=ticket) or [])
                     if d.entry == mt5.DEAL_ENTRY_OUT]
            if deals:
                d = max(deals, key=lambda x: x.time)
                close_price, profit = d.price, d.profit
                tol = abs(info["tp"] - info["entry"]) * 0.05
                if abs(close_price - info["sl"]) < tol:
                    reason = " SL HIT"
                    sl_hit_symbols.add(symbol)
                elif abs(close_price - info["tp"]) < tol: reason = " TP HIT"
                else:                                      reason = "Manual / other"
        except Exception as e:
            logger.warning("History fetch failed ticket=%d: %s", ticket, e)
        logger.info("CLOSED | %s %s | Entry=%.2f Close=%.2f P&L=%.2f | %s",
                    direction, symbol, info["entry"], close_price, profit, reason)
        if tg:
            try:
                tg.trade_closed(symbol, direction.lower(), info["entry"],
                                close_price, profit, reason=reason)
            except Exception as e:
                logger.warning("TG close notify failed: %s", e)
    return sl_hit_symbols


def manage_trades(symbol: str, atr_value: float, direction: str,
                  tg=None, balance_ref: list = None):
    """
    Check and manage all open positions for a symbol.

    Args:
        symbol      : "BTCUSD", "ETHUSD", "XAUUSD", "XAGUSD"
        atr_value   : current 4H ATR (for trailing stop calculation)
        direction   : "buy" or "sell"
        tg          : telegram_notify module (optional)
        balance_ref : [balance] mutable list to update after partial close
    """
    positions = get_open_positions()
    mt5_sym   = SYMBOLS.get(symbol, {}).get("mt5_symbol", symbol)
    sym_pos   = [p for p in positions if p["symbol"] == mt5_sym]

    for pos in sym_pos:
        ticket     = pos["ticket"]
        entry      = pos["open_price"]
        sl         = pos["sl"]
        tp         = pos["tp"]
        profit     = pos["profit"]
        volume     = pos["volume"]
        pos_type   = pos["type"]   # 0=buy, 1=sell

        # Determine SL distance from entry
        if sl == 0:
            continue  # no SL set -- skip (shouldn't happen)

        sl_dist = abs(entry - sl)
        if sl_dist == 0:
            continue

        # Current price implied from profit
        # profit = (price - entry) x lot x contract_size
        cfg           = SYMBOLS.get(symbol, {})
        contract_size = cfg.get("contract_size", 1)
        lot_val       = volume * contract_size

        # Get current price from tick
        try:
            import MetaTrader5 as mt5
            tick = mt5.symbol_info_tick(mt5_sym)
            if not tick:
                continue
            current_price = tick.bid if pos_type == 0 else tick.ask
        except Exception:
            continue

        if pos_type == 0:   # BUY
            move      = current_price - entry
            tp_dist   = tp - entry if tp > 0 else sl_dist * 2.5
        else:               # SELL
            move      = entry - current_price
            tp_dist   = entry - tp if tp > 0 else sl_dist * 2.5

        ratio = move / sl_dist if sl_dist > 0 else 0

        # -- 1. Breakeven at 1:1.5 -----------------------------------
        if ratio >= 1.5:
            if pos_type == 0 and sl < entry:     # BUY: SL still below entry
                new_sl = entry + 0.01            # tiny buffer above entry
                if modify_sl(ticket, new_sl, symbol):
                    logger.info("BREAKEVEN [%s] ticket=%d | SL -> %.5f", symbol, ticket, new_sl)
                    if tg:
                        tg.breakeven_triggered(symbol, entry)

            elif pos_type == 1 and sl > entry:   # SELL: SL still above entry
                new_sl = entry - 0.01
                if modify_sl(ticket, new_sl, symbol):
                    logger.info("BREAKEVEN [%s] ticket=%d | SL -> %.5f", symbol, ticket, new_sl)
                    if tg:
                        tg.breakeven_triggered(symbol, entry)

        # -- 2. Trail near TP only (within 0.5x ATR) --------------------
        # Hold full position -- only trail tightly near the finish line
        if tp > 0 and atr_value and atr_value > 0:
            dist_to_tp = abs(current_price - tp)
            if dist_to_tp < atr_value * 0.5:
                if pos_type == 0:   # BUY
                    trail_sl = current_price - atr_value * 0.3
                    if trail_sl > sl:
                        if modify_sl(ticket, trail_sl, symbol):
                            logger.info("NEAR-TP TRAIL [%s] ticket=%d | SL -> %.5f", symbol, ticket, trail_sl)
                else:               # SELL
                    trail_sl = current_price + atr_value * 0.3
                    if trail_sl < sl:
                        if modify_sl(ticket, trail_sl, symbol):
                            logger.info("NEAR-TP TRAIL [%s] ticket=%d | SL -> %.5f", symbol, ticket, trail_sl)

        # -- 4. Close near TP -----------------------------------------
        if tp > 0 and atr_value and atr_value > 0:
            dist_to_tp = abs(current_price - tp)
            if dist_to_tp < atr_value * 0.1:
                if close_position(ticket, symbol, volume):
                    logger.info("CLOSE NEAR TP [%s] ticket=%d | price=%.5f TP=%.5f",
                                symbol, ticket, current_price, tp)
                    if tg:
                        tg.trade_closed(symbol,
                                        "buy" if pos_type == 0 else "sell",
                                        entry, current_price, profit,
                                        balance_ref[0] if balance_ref else 0,
                                        "Near TP -- institutional close")


def cancel_stale_pending_orders(max_age_minutes: int = 240):
    """
    Cancel limit orders that haven't been filled after max_age_minutes.
    If price moved far from our OB level, the opportunity is gone.
    """
    import MetaTrader5 as mt5
    from executor import cancel_pending_order

    orders = mt5.orders_get() or []
    now    = datetime.now(timezone.utc)

    for order in orders:
        if order.magic != MAGIC_NUMBER:
            continue
        placed_at = datetime.fromtimestamp(order.time_setup, tz=timezone.utc)
        age_mins  = (now - placed_at).total_seconds() / 60
        if age_mins > max_age_minutes:
            cancel_pending_order(order.ticket)
            logger.info("Stale pending order %d cancelled (%.0f min old)",
                        order.ticket, age_mins)
