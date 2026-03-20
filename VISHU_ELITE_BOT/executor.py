"""
VISHU ELITE BOT — Trade Executor
Opens, closes, and modifies trades on MetaTrader 5.
Uses the same pattern as the reference trading_automation/executor.py.
"""

import logging
import MetaTrader5 as mt5
from config import SYMBOLS, MAGIC_NUMBER

logger = logging.getLogger("executor")


def _resolve_mt5_symbol(symbol: str) -> str:
    """Return MT5 symbol name (e.g. BTCUSDm) for logical name (e.g. BTCUSD)."""
    return SYMBOLS.get(symbol, {}).get("mt5_symbol", symbol)


def _ensure_symbol_active(mt5_symbol: str) -> bool:
    """Make sure symbol is visible in Market Watch. Returns True on success."""
    info = mt5.symbol_info(mt5_symbol)
    if info is None:
        mt5.symbol_select(mt5_symbol, True)
        info = mt5.symbol_info(mt5_symbol)
    return info is not None


def open_trade(
    symbol:  str,
    action:  str,    # 'BUY' or 'SELL' (case-insensitive)
    lot:     float,
    sl:      float,
    tp:      float,
    comment: str = "VishuEliteBot",
) -> dict:
    """
    Open a market order on MT5.

    Returns:
        {
            "success":     bool,
            "ticket":      int | None,
            "entry_price": float,
            "message":     str,
        }
    """
    mt5_symbol = _resolve_mt5_symbol(symbol)

    if not _ensure_symbol_active(mt5_symbol):
        return {
            "success":     False,
            "ticket":      None,
            "entry_price": 0.0,
            "message":     f"Symbol {mt5_symbol} not found in Market Watch",
        }

    tick = mt5.symbol_info_tick(mt5_symbol)
    if tick is None:
        return {
            "success":     False,
            "ticket":      None,
            "entry_price": 0.0,
            "message":     f"Cannot get tick for {mt5_symbol}",
        }

    action_upper = action.upper()
    order_type   = mt5.ORDER_TYPE_BUY  if action_upper == "BUY" else mt5.ORDER_TYPE_SELL
    price        = tick.ask            if action_upper == "BUY" else tick.bid

    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       mt5_symbol,
        "volume":       float(lot),
        "type":         order_type,
        "price":        price,
        "sl":           float(sl),
        "tp":           float(tp),
        "deviation":    20,
        "magic":        MAGIC_NUMBER,
        "comment":      comment,
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)

    if result is None:
        msg = f"order_send returned None — MT5 may be disconnected. Error: {mt5.last_error()}"
        logger.error(msg)
        return {"success": False, "ticket": None, "entry_price": 0.0, "message": msg}

    if result.retcode == mt5.TRADE_RETCODE_DONE:
        logger.info(
            "TRADE OPENED | %s %s | Lot=%.2f | Entry=%.5f | SL=%.5f | TP=%.5f | Ticket=%d",
            action_upper, mt5_symbol, lot, result.price, sl, tp, result.order,
        )
        return {
            "success":     True,
            "ticket":      result.order,
            "entry_price": result.price,
            "message":     "OK",
        }
    else:
        msg = (
            f"order_send FAILED | retcode={result.retcode} | "
            f"comment={result.comment} | symbol={mt5_symbol}"
        )
        logger.error(msg)
        return {"success": False, "ticket": None, "entry_price": 0.0, "message": msg}


def close_trade(ticket: int, symbol: str) -> bool:
    """
    Close a specific open position by ticket number.
    Returns True on success.
    """
    mt5_symbol = _resolve_mt5_symbol(symbol)

    # Find position
    position = None
    for pos in (mt5.positions_get(symbol=mt5_symbol) or []):
        if pos.ticket == ticket:
            position = pos
            break

    if position is None:
        logger.warning("close_trade: ticket %d not found for %s", ticket, mt5_symbol)
        return False

    # Close is opposite order type
    order_type = mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
    tick       = mt5.symbol_info_tick(mt5_symbol)
    if tick is None:
        logger.error("close_trade: cannot get tick for %s", mt5_symbol)
        return False

    price = tick.bid if order_type == mt5.ORDER_TYPE_SELL else tick.ask

    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       mt5_symbol,
        "volume":       position.volume,
        "type":         order_type,
        "position":     ticket,
        "price":        price,
        "deviation":    20,
        "magic":        MAGIC_NUMBER,
        "comment":      "VishuEliteBot close",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result is None:
        logger.error("close_trade: order_send returned None for ticket %d", ticket)
        return False

    if result.retcode == mt5.TRADE_RETCODE_DONE:
        logger.info("TRADE CLOSED | Ticket=%d | Symbol=%s", ticket, mt5_symbol)
        return True
    else:
        logger.error(
            "close_trade FAILED | Ticket=%d | retcode=%d | %s",
            ticket, result.retcode, result.comment,
        )
        return False


def close_all_for_symbol(symbol: str) -> int:
    """
    Close all open positions for a symbol that were opened by this bot.
    Returns count of successfully closed positions.
    """
    mt5_symbol = _resolve_mt5_symbol(symbol)
    positions  = mt5.positions_get(symbol=mt5_symbol) or []
    bot_pos    = [p for p in positions if p.magic == MAGIC_NUMBER]

    closed = 0
    for pos in bot_pos:
        if close_trade(pos.ticket, symbol):
            closed += 1

    if closed:
        logger.info("Closed %d position(s) for %s", closed, symbol)
    return closed


def close_all_positions_eod() -> int:
    """
    End-of-day: close ALL open positions (any bot/magic) and cancel ALL pending orders.
    Called at 21:30 IST (16:00 UTC) — no waiting for SL/TP.
    Returns total positions closed.
    """
    import MetaTrader5 as _mt5
    closed = 0

    # Close all open positions
    positions = _mt5.positions_get() or []
    for pos in positions:
        sym = pos.symbol.replace("m", "") if pos.symbol.endswith("m") else pos.symbol
        if close_trade(pos.ticket, sym):
            closed += 1
            logger.info("EOD CLOSE | %s | Ticket=%d | P&L=%.2f", pos.symbol, pos.ticket, pos.profit)

    # Cancel all pending orders
    orders = _mt5.orders_get() or []
    for order in orders:
        req = {
            "action": _mt5.TRADE_ACTION_REMOVE,
            "order":  order.ticket,
        }
        result = _mt5.order_send(req)
        if result and result.retcode == _mt5.TRADE_RETCODE_DONE:
            logger.info("EOD CANCEL | Pending #%d cancelled", order.ticket)
        else:
            logger.warning("EOD CANCEL FAILED | Pending #%d", order.ticket)

    logger.info("EOD close complete — %d position(s) closed, %d pending(s) cancelled", closed, len(orders))
    return closed


def modify_sl(ticket: int, symbol: str, new_sl: float) -> bool:
    """
    Modify the stop-loss of an open position.
    Returns True on success.
    """
    mt5_symbol = _resolve_mt5_symbol(symbol)

    # Find position to get current TP
    position = None
    for pos in (mt5.positions_get(symbol=mt5_symbol) or []):
        if pos.ticket == ticket:
            position = pos
            break

    if position is None:
        logger.warning("modify_sl: ticket %d not found", ticket)
        return False

    request = {
        "action":   mt5.TRADE_ACTION_SLTP,
        "symbol":   mt5_symbol,
        "position": ticket,
        "sl":       float(new_sl),
        "tp":       position.tp,
    }

    result = mt5.order_send(request)
    if result is None:
        logger.error("modify_sl: order_send returned None for ticket %d", ticket)
        return False

    if result.retcode == mt5.TRADE_RETCODE_DONE:
        logger.info(
            "SL MODIFIED | Ticket=%d | New SL=%.5f",
            ticket, new_sl,
        )
        return True
    else:
        logger.error(
            "modify_sl FAILED | Ticket=%d | retcode=%d | %s",
            ticket, result.retcode, result.comment,
        )
        return False


def get_position_profit(ticket: int, symbol: str) -> float:
    """Return current unrealized profit for a position. 0.0 if not found."""
    mt5_symbol = _resolve_mt5_symbol(symbol)
    for pos in (mt5.positions_get(symbol=mt5_symbol) or []):
        if pos.ticket == ticket:
            return pos.profit
    return 0.0
