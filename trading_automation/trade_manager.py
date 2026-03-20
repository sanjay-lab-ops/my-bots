"""
Trade Manager — handles open positions every tick.

Features:
  1. BREAKEVEN  — when trade hits 1:1 profit, move SL to entry + buffer
  2. TRAILING STOP — as price moves further, drag SL to lock in profits
  3. FORCE CLOSE — if session ends and CARRY_TO_LAST_SESSION=False, close
"""

import os
import json
import logging
import MetaTrader5 as mt5
from config import SYMBOLS, ATR_SL_MULTIPLIER, RR_RATIO

_COP_FILE = os.path.join(os.path.dirname(__file__), "close_on_profit.json")

def _load_cop() -> list:
    try:
        if os.path.exists(_COP_FILE):
            return json.load(open(_COP_FILE)).get("tickets", [])
    except Exception:
        pass
    return []

def _save_cop(tickets: list):
    with open(_COP_FILE, "w") as f:
        json.dump({"tickets": tickets}, f)

logger = logging.getLogger("trade_manager")

MAGIC = 20260318

# ── Closed position tracker (detects SL/TP hits) ─────────────────────────────
_tracked: dict = {}


def snapshot_positions(symbol: str, positions: list):
    for pos in positions:
        _tracked[pos.ticket] = {
            "symbol": symbol, "type": pos.type,
            "entry": pos.price_open, "sl": pos.sl, "tp": pos.tp,
        }


def detect_closed_positions(current_tickets: set, notify_closed_fn=None):
    """Fires Telegram notify for any position that closed since last tick."""
    for ticket in set(_tracked.keys()) - current_tickets:
        info      = _tracked.pop(ticket)
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
                    direction, info["symbol"], info["entry"], close_price, profit, reason)
        if notify_closed_fn:
            try:
                notify_closed_fn(info["symbol"], direction, info["entry"], close_price, profit, reason=reason)
            except Exception as e:
                logger.warning("TG close notify failed: %s", e)

# Trailing step: move SL every time price moves this many × ATR beyond last SL
TRAIL_ATR_MULT  = 0.8   # trail SL at 0.8× ATR behind price
BREAKEVEN_BUFFER_PIPS = 2  # move SL to entry + 2 pips when BE triggers


def _modify_sl(ticket: int, symbol: str, new_sl: float) -> bool:
    """Modify the SL of an open position."""
    mt5_sym = SYMBOLS.get(symbol, {}).get("mt5_symbol", symbol)
    positions = mt5.positions_get(symbol=mt5_sym) or []
    pos = next((p for p in positions if p.ticket == ticket), None)
    if pos is None:
        return False

    request = {
        "action":   mt5.TRADE_ACTION_SLTP,
        "position": ticket,
        "sl":       round(new_sl, 2),
        "tp":       pos.tp,
    }
    result = mt5.order_send(request)
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        logger.info("SL modified | Ticket=%d | NewSL=%.2f", ticket, new_sl)
        return True
    else:
        rc = result.retcode if result else "None"
        logger.warning("SL modify failed | Ticket=%d | retcode=%s", ticket, rc)
        return False


def manage_open_positions(atr_map: dict):
    """
    Called every tick. Applies breakeven + trailing stop to all bot positions.

    atr_map: dict of {symbol: atr_value_4h}
    e.g. {"BTCUSD": 850.0, "XAUUSD": 42.5}
    """
    for symbol in SYMBOLS:
        mt5_sym = SYMBOLS[symbol].get("mt5_symbol", symbol)
        atr     = atr_map.get(symbol, 0)
        if atr <= 0:
            continue

        positions = mt5.positions_get(symbol=mt5_sym) or []
        bot_positions = [p for p in positions if p.magic == MAGIC]

        cop_tickets = _load_cop()

        for pos in bot_positions:
            ticket     = pos.ticket

            # ── Close-on-first-profit ────────────────────────────────
            if ticket in cop_tickets and pos.profit > 0:
                mt5_sym = SYMBOLS.get(symbol, {}).get("mt5_symbol", symbol)
                close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
                tick = mt5.symbol_info_tick(mt5_sym)
                if tick:
                    price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask
                    req = {
                        "action": mt5.TRADE_ACTION_DEAL, "symbol": mt5_sym,
                        "volume": pos.volume, "type": close_type,
                        "position": ticket, "price": price,
                        "deviation": 20, "magic": MAGIC,
                        "comment": "Close-on-profit",
                        "type_time": mt5.ORDER_TIME_GTC,
                        "type_filling": mt5.ORDER_FILLING_IOC,
                    }
                    result = mt5.order_send(req)
                    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                        logger.info("CLOSE-ON-PROFIT | ticket=%d | profit=%.2f", ticket, pos.profit)
                        cop_tickets.remove(ticket)
                        _save_cop(cop_tickets)
                continue
            entry      = pos.price_open
            current_sl = pos.sl
            current_tp = pos.tp
            price      = pos.price_current
            is_buy     = pos.type == mt5.ORDER_TYPE_BUY

            sl_distance   = atr * ATR_SL_MULTIPLIER
            be_trigger    = sl_distance             # 1:1 distance from entry
            trail_distance = atr * TRAIL_ATR_MULT   # trail this far behind price

            if is_buy:
                profit_pts    = price - entry
                be_price      = entry + BREAKEVEN_BUFFER_PIPS / 10
                trail_sl      = price - trail_distance

                # 1. Breakeven — move SL to entry when 1:1 reached
                if profit_pts >= be_distance(be_trigger) and current_sl < be_price:
                    logger.info(
                        "BREAKEVEN [%s] BUY | Entry=%.2f | Price=%.2f | Moving SL to %.2f",
                        symbol, entry, price, be_price,
                    )
                    _modify_sl(ticket, symbol, be_price)

                # 2. Trailing stop — only near TP (within 0.5× SL distance of TP)
                elif current_tp > 0 and (current_tp - price) < sl_distance * 0.5 and trail_sl > current_sl:
                    logger.info(
                        "TRAIL SL [%s] BUY | Price=%.2f | OldSL=%.2f → NewSL=%.2f",
                        symbol, price, current_sl, trail_sl,
                    )
                    _modify_sl(ticket, symbol, trail_sl)

            else:  # SELL
                profit_pts = entry - price
                be_price   = entry - BREAKEVEN_BUFFER_PIPS / 10
                trail_sl   = price + trail_distance

                # 1. Breakeven
                if profit_pts >= be_distance(be_trigger) and current_sl > be_price:
                    logger.info(
                        "BREAKEVEN [%s] SELL | Entry=%.2f | Price=%.2f | Moving SL to %.2f",
                        symbol, entry, price, be_price,
                    )
                    _modify_sl(ticket, symbol, be_price)

                # 2. Trailing stop — only near TP (within 0.5× SL distance of TP)
                elif current_tp > 0 and (price - current_tp) < sl_distance * 0.5 and trail_sl < current_sl:
                    logger.info(
                        "TRAIL SL [%s] SELL | Price=%.2f | OldSL=%.2f → NewSL=%.2f",
                        symbol, price, current_sl, trail_sl,
                    )
                    _modify_sl(ticket, symbol, trail_sl)


def be_distance(sl_distance: float) -> float:
    """Return the price move needed to trigger breakeven (= 1.5× SL distance)."""
    return sl_distance * 1.5
