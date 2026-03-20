"""
VISHU ELITE BOT — Risk Management
Lot size calculation, SL/TP calculation, and daily loss limit check.

Lot Tiers (safe for small accounts):
  BTCUSD: balance ≤ $100 → 0.01, ≤ $300 → 0.02, ≤ $600 → 0.05, else 0.10
  XAUUSD: balance ≤ $200 → 0.01, ≤ $500 → 0.02, ≤ $1000 → 0.05, else 0.10

SL = ATR(4H) × 1.5
TP = SL × 2.0 (2:1 R:R)
"""

import logging
import math
from config import (
    SYMBOLS, ATR_SL_MULT, RR_RATIO, DAILY_LOSS_LIMIT
)

logger = logging.getLogger("risk")


def get_lot_size(symbol: str, balance: float) -> float:
    """
    Return fixed-tier lot size based on symbol and account balance.
    Tiers are deliberately conservative to protect small accounts.
    """
    cfg      = SYMBOLS.get(symbol, {})
    min_lot  = cfg.get("min_lot",  0.01)
    max_lot  = cfg.get("max_lot",  1.0)
    lot_step = cfg.get("lot_step", 0.01)

    if symbol == "BTCUSD":
        if balance <= 100:
            raw = 0.01
        elif balance <= 300:
            raw = 0.02
        elif balance <= 600:
            raw = 0.05
        else:
            raw = 0.10

    elif symbol == "XAUUSD":
        if balance <= 200:
            raw = 0.01
        elif balance <= 500:
            raw = 0.02
        elif balance <= 1000:
            raw = 0.05
        else:
            raw = 0.10

    else:
        raw = min_lot

    # Clamp to symbol limits and round to lot_step
    raw = max(min_lot, min(max_lot, raw))
    lot = round(math.floor(raw / lot_step) * lot_step, 2)

    logger.info(
        "LOT SIZE [%s]: balance=$%.2f → %.2f lots",
        symbol, balance, lot,
    )
    return lot


def calculate_sl_tp(
    action:      str,
    entry_price: float,
    atr_val:     float,
    symbol:      str,
) -> tuple:
    """
    Calculate SL and TP based on ATR.

    SL distance = ATR × ATR_SL_MULT  (default 1.5)
    TP distance = SL distance × RR_RATIO (default 2.0)

    Returns: (sl_price: float, tp_price: float)
    """
    sl_distance = atr_val * ATR_SL_MULT
    tp_distance = sl_distance * RR_RATIO

    if action.upper() == "BUY":
        sl = entry_price - sl_distance
        tp = entry_price + tp_distance
    else:  # SELL
        sl = entry_price + sl_distance
        tp = entry_price - tp_distance

    # Round appropriately: Gold to 2 decimals, BTC to 1 decimal
    decimals = 2 if "XAU" in symbol else 1
    sl = round(sl, decimals)
    tp = round(tp, decimals)

    logger.info(
        "SL/TP [%s %s]: Entry=%.2f | SL=%.2f (dist=%.2f) | TP=%.2f | ATR=%.2f | RR=1:%.1f",
        action.upper(), symbol, entry_price, sl, sl_distance, tp, atr_val, RR_RATIO,
    )
    return sl, tp


def is_daily_loss_limit_hit(day_pnl: float) -> bool:
    """
    Check if daily P&L has breached the loss limit.
    Returns True if trading should be halted for the day.
    """
    if day_pnl <= DAILY_LOSS_LIMIT:
        logger.warning(
            "DAILY LOSS LIMIT HIT: P&L=%.2f <= limit=%.2f — halting all trading",
            day_pnl, DAILY_LOSS_LIMIT,
        )
        return True
    return False


def check_trade_risk(
    symbol:      str,
    balance:     float,
    lot:         float,
    atr_val:     float,
) -> bool:
    """
    Safety check: verify the trade risk is not account-destroying.
    Returns True if trade is safe to proceed.
    Blocks if SL risk > 75% of balance.
    """
    cfg           = SYMBOLS.get(symbol, {})
    contract_size = cfg.get("contract_size", 1)
    min_lot       = cfg.get("min_lot", 0.01)

    if atr_val <= 0 or balance <= 0:
        return True  # can't calculate, allow trade

    sl_risk_usd = lot * atr_val * ATR_SL_MULT * contract_size
    risk_pct    = (sl_risk_usd / balance) * 100

    min_lot_risk_usd = min_lot * atr_val * ATR_SL_MULT * contract_size
    min_lot_risk_pct = (min_lot_risk_usd / balance) * 100

    if min_lot_risk_pct > 20:
        logger.warning(
            "HIGH RISK WARNING [%s]: min lot risks %.1f%% of $%.2f",
            symbol, min_lot_risk_pct, balance,
        )
        # Silver blocked via MIN_BALANCE_TO_TRADE in config

    if risk_pct > 20:
        logger.warning(
            "HIGH RISK WARNING [%s]: %.2f lots risks $%.2f (%.1f%% of $%.2f balance)",
            symbol, lot, sl_risk_usd, risk_pct, balance,
        )
    else:
        logger.info(
            "Risk check OK [%s]: %.2f lots risks $%.2f (%.1f%% of $%.2f balance)",
            symbol, lot, sl_risk_usd, risk_pct, balance,
        )
    return True
