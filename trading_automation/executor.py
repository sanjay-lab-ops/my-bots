"""
Trade executor — opens and closes positions on Exness MT5.
"""

import logging
import MetaTrader5 as mt5
from config import SYMBOLS

logger = logging.getLogger("executor")


def _resolve_symbol(symbol: str) -> str:
    """Return the MT5 symbol name (e.g. BTCUSDm) for a logical name."""
    return SYMBOLS.get(symbol, {}).get("mt5_symbol", symbol)


def open_trade(
    symbol:   str,
    action:   str,     # 'buy' or 'sell'
    lot:      float,
    sl:       float,
    tp:       float,
    comment:  str = "VishuBot",
) -> dict:
    """
    Open a market order.
    Returns dict with success flag, ticket, and message.
    """
    mt5_symbol = _resolve_symbol(symbol)
    info = mt5.symbol_info(mt5_symbol)
    if info is None:
        mt5.symbol_select(mt5_symbol, True)
        info = mt5.symbol_info(mt5_symbol)

    if info is None:
        return {"success": False, "ticket": None, "message": f"Symbol {mt5_symbol} not found"}

    tick = mt5.symbol_info_tick(mt5_symbol)
    if tick is None:
        return {"success": False, "ticket": None, "message": "Cannot get tick data"}

    order_type = mt5.ORDER_TYPE_BUY if action == "buy" else mt5.ORDER_TYPE_SELL
    price      = tick.ask if action == "buy" else tick.bid

    request = {
        "action":     mt5.TRADE_ACTION_DEAL,
        "symbol":     mt5_symbol,
        "volume":     lot,
        "type":       order_type,
        "price":      price,
        "sl":         sl,
        "tp":         tp,
        "deviation":  20,
        "magic":      20260318,   # unique bot identifier
        "comment":    comment,
        "type_time":  mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)

    if result.retcode == mt5.TRADE_RETCODE_DONE:
        logger.info(
            "Trade opened | %s %s | Lot=%.2f | Entry=%.5f | SL=%.5f | TP=%.5f | Ticket=%s",
            action.upper(), mt5_symbol, lot, price, sl, tp, result.order,
        )
        return {"success": True, "ticket": result.order, "entry_price": price, "message": "OK"}
    else:
        msg = f"order_send failed | retcode={result.retcode} | comment={result.comment}"
        logger.error(msg)
        return {"success": False, "ticket": None, "message": msg}


def close_trade(ticket: int, symbol: str, lot: float) -> bool:
    """Close a specific open position by ticket."""
    mt5_symbol = _resolve_symbol(symbol)
    position = None
    for pos in (mt5.positions_get(symbol=mt5_symbol) or []):
        if pos.ticket == ticket:
            position = pos
            break

    if position is None:
        logger.warning("Position %d not found for close.", ticket)
        return False

    order_type = mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
    tick       = mt5.symbol_info_tick(mt5_symbol)
    price      = tick.bid if order_type == mt5.ORDER_TYPE_SELL else tick.ask

    request = {
        "action":     mt5.TRADE_ACTION_DEAL,
        "symbol":     mt5_symbol,
        "volume":     lot,
        "type":       order_type,
        "position":   ticket,
        "price":      price,
        "deviation":  20,
        "magic":      20260318,
        "comment":    "VishuBot close",
        "type_time":  mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        logger.info("Position %d closed successfully.", ticket)
        return True
    else:
        logger.error("Close failed | retcode=%d | %s", result.retcode, result.comment)
        return False


def close_all_for_symbol(symbol: str) -> int:
    """Close all open positions for a symbol. Returns count closed."""
    mt5_symbol = _resolve_symbol(symbol)
    positions  = mt5.positions_get(symbol=mt5_symbol) or []
    closed = 0
    for pos in positions:
        if close_trade(pos.ticket, symbol, pos.volume):
            closed += 1
    return closed
