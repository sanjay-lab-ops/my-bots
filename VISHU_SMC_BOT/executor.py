"""
Trade Executor -- Institutional style order placement.

Key difference from retail:
  RETAIL  -> places MARKET ORDER chasing current price
  THIS BOT -> places LIMIT ORDER at Order Block, waits for price to come to us

When price returns to our order block and fills our limit order,
we're entering at the same price the institution originally placed their orders.
This gives us the same entry as BlackRock -- not chasing them.
"""

import logging
import MetaTrader5 as mt5
from config import SYMBOLS, MAGIC_NUMBER

logger = logging.getLogger("executor")


def _resolve(symbol: str) -> str:
    return SYMBOLS.get(symbol, {}).get("mt5_symbol", symbol)


def _ensure_selected(mt5_symbol: str) -> bool:
    if mt5.symbol_info(mt5_symbol) is None:
        mt5.symbol_select(mt5_symbol, True)
    return mt5.symbol_info(mt5_symbol) is not None


def place_limit_order(symbol: str, direction: str, lot: float,
                      price: float, sl: float, tp: float,
                      comment: str = "SMC-OB") -> int | None:
    """
    Place a PENDING LIMIT ORDER at the order block level.
    Bot waits for price to return -- institutional execution style.

    Returns order ticket (int) or None if failed.
    """
    mt5_sym = _resolve(symbol)
    if not _ensure_selected(mt5_sym):
        logger.error("Cannot select symbol %s", mt5_sym)
        return None

    order_type = mt5.ORDER_TYPE_BUY_LIMIT if direction == "buy" else mt5.ORDER_TYPE_SELL_LIMIT

    request = {
        "action":       mt5.TRADE_ACTION_PENDING,
        "symbol":       mt5_sym,
        "volume":       lot,
        "type":         order_type,
        "price":        round(price, 5),
        "sl":           round(sl, 5),
        "tp":           round(tp, 5),
        "deviation":    20,
        "magic":        MAGIC_NUMBER,
        "comment":      comment,
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_RETURN,  # Exness requires RETURN for pending orders
    }

    result = mt5.order_send(request)
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        logger.info("Limit order placed | %s %s | Price=%.5f | Lot=%.2f | Ticket=%d",
                    direction.upper(), mt5_sym, price, lot, result.order)
        return result.order
    else:
        retcode = result.retcode if result else "N/A"
        err     = result.comment if result else mt5.last_error()
        logger.error("Limit order failed | %s | retcode=%s | %s", mt5_sym, retcode, err)
        print(f"      -> retcode={retcode} | {err}")
        return None


def place_market_order(symbol: str, direction: str, lot: float,
                       sl: float, tp: float, comment: str = "SMC-MKT") -> int | None:
    """
    Place a market order (fallback for momentum entries / news trades).
    Returns position ticket or None.
    """
    mt5_sym = _resolve(symbol)
    if not _ensure_selected(mt5_sym):
        return None

    tick       = mt5.symbol_info_tick(mt5_sym)
    if not tick:
        logger.error("Cannot get tick for %s", mt5_sym)
        return None

    price      = tick.ask if direction == "buy" else tick.bid
    order_type = mt5.ORDER_TYPE_BUY if direction == "buy" else mt5.ORDER_TYPE_SELL

    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       mt5_sym,
        "volume":       lot,
        "type":         order_type,
        "price":        price,
        "sl":           round(sl, 5),
        "tp":           round(tp, 5),
        "deviation":    20,
        "magic":        MAGIC_NUMBER,
        "comment":      comment,
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        logger.info("Market order filled | %s %s | Entry=%.5f | Lot=%.2f | Ticket=%d",
                    direction.upper(), mt5_sym, price, lot, result.order)
        return result.order
    else:
        err = result.comment if result else mt5.last_error()
        logger.error("Market order failed | %s | %s", mt5_sym, err)
        return None


def cancel_pending_order(ticket: int) -> bool:
    """Cancel a pending limit order by ticket."""
    request = {
        "action": mt5.TRADE_ACTION_REMOVE,
        "order":  ticket,
    }
    result = mt5.order_send(request)
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        logger.info("Pending order %d cancelled.", ticket)
        return True
    logger.warning("Cancel failed for order %d: %s",
                   ticket, result.comment if result else mt5.last_error())
    return False


def modify_sl(ticket: int, new_sl: float, symbol: str) -> bool:
    """Move stop loss of an open position."""
    mt5_sym   = _resolve(symbol)
    positions = mt5.positions_get(symbol=mt5_sym) or []
    position  = next((p for p in positions if p.ticket == ticket), None)

    if not position:
        logger.warning("modify_sl: position %d not found", ticket)
        return False

    request = {
        "action":   mt5.TRADE_ACTION_SLTP,
        "symbol":   mt5_sym,
        "position": ticket,
        "sl":       round(new_sl, 5),
        "tp":       position.tp,
        "magic":    MAGIC_NUMBER,
    }
    result = mt5.order_send(request)
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        logger.info("SL modified | ticket=%d | new_sl=%.5f", ticket, new_sl)
        return True
    logger.warning("SL modify failed for %d: %s",
                   ticket, result.comment if result else mt5.last_error())
    return False


def close_position(ticket: int, symbol: str, volume: float) -> bool:
    """Close an open position by ticket."""
    mt5_sym   = _resolve(symbol)
    positions = mt5.positions_get(symbol=mt5_sym) or []
    position  = next((p for p in positions if p.ticket == ticket), None)

    if not position:
        logger.warning("close_position: ticket %d not found", ticket)
        return False

    close_type = mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
    tick       = mt5.symbol_info_tick(mt5_sym)
    if not tick:
        return False
    price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask

    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       mt5_sym,
        "volume":       volume,
        "type":         close_type,
        "position":     ticket,
        "price":        price,
        "deviation":    20,
        "magic":        MAGIC_NUMBER,
        "comment":      "SMC-CLOSE",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        logger.info("Position %d closed.", ticket)
        return True
    logger.error("Close failed for %d: %s",
                 ticket, result.comment if result else mt5.last_error())
    return False


def close_partial(ticket: int, symbol: str, volume: float) -> bool:
    """Close partial volume of a position (lock in profits, let rest run)."""
    return close_position(ticket, symbol, volume)
