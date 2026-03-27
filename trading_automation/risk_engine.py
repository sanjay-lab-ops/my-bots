"""
Risk Engine — auto lot size + SL/TP calculation.

Uses ATR-based proper 1% risk formula:
  lot = (balance × risk%) ÷ (ATR × SL_multiplier × contract_size)

Minimum lots enforced per pair (accounts too small for formula):
  BTCUSD: min 0.01 (safe from $200+, risky below that)
  XAUUSD: min 0.01 (safe from $1000+, risky below that)

For demo/small accounts — bot logs a WARNING if risk exceeds 5% per trade.
"""

import logging
import math
from config import ATR_SL_MULTIPLIER, RR_RATIO, SYMBOLS, RISK_PERCENT, RISK_MODE

logger = logging.getLogger("risk_engine")

MIN_PROFIT_TARGET = 3.0  # minimum $ profit expected per trade — boost lot if target too small


def calculate_lot(balance: float, symbol: str, atr_4h: float = None,
                  day_lot_multiplier: float = 1.0) -> float:
    """
    Return lot size based on balance, pair, and ATR.
    Uses proper 1% risk formula when ATR is provided.
    Falls back to safe fixed tiers for small accounts.
    """
    cfg           = SYMBOLS.get(symbol, {})
    min_lot       = cfg.get("min_lot", 0.01)
    max_lot       = cfg.get("max_lot", 1.0)
    lot_step      = cfg.get("lot_step", 0.01)
    contract_size = cfg.get("contract_size", 1)

    # ── Proper ATR-based formula ─────────────────────────────────
    if atr_4h and atr_4h > 0:
        risk_amount  = balance * (RISK_PERCENT / 100)
        sl_dollar    = atr_4h * ATR_SL_MULTIPLIER * contract_size
        raw          = risk_amount / sl_dollar if sl_dollar > 0 else min_lot
    else:
        # ── Safe fixed tiers (pair-specific) ────────────────────
        if symbol == "BTCUSD":
            if balance <= 100:    raw = 0.01
            elif balance <= 300:  raw = 0.02
            elif balance <= 600:  raw = 0.05
            elif balance <= 1000: raw = 0.10
            elif balance <= 2000: raw = 0.20
            elif balance <= 5000: raw = 0.50
            else:                 raw = 1.0
        elif symbol == "ETHUSD":
            if balance <= 100:    raw = 0.1
            elif balance <= 300:  raw = 0.2
            elif balance <= 600:  raw = 0.3
            elif balance <= 1000: raw = 0.5
            elif balance <= 2000: raw = 1.0
            else:                 raw = 2.0
        elif symbol == "XAUUSD":
            if balance <= 500:    raw = 0.01
            elif balance <= 800:  raw = 0.02
            elif balance <= 1200: raw = 0.03
            else:                 raw = 0.05   # max 0.05 — safe for all balance levels
        else:  # XAGUSD — contract_size=5000, very sensitive, keep lots tiny
            if balance <= 2000:   raw = 0.01
            else:                 raw = 0.02   # max 0.02 — 0.05 risks $800+ at small SL

    # ── Target-aware boost ───────────────────────────────────────
    # If expected profit is too small (< MIN_PROFIT_TARGET), boost lot
    # so the trade is worth taking. Cap boost at 2× risk-based lot.
    if atr_4h and atr_4h > 0:
        tp_distance      = atr_4h * ATR_SL_MULTIPLIER * RR_RATIO
        expected_profit  = raw * tp_distance * contract_size
        if expected_profit < MIN_PROFIT_TARGET and raw < max_lot:
            boosted = MIN_PROFIT_TARGET / (tp_distance * contract_size) if tp_distance > 0 else raw
            raw = min(boosted, raw * 2)   # never more than 2× the risk-based lot

    # ── Hard risk cap — block trade if minimum lot risks > 50% of balance ──
    # Gold 0.01 lot = $94-160 risk. At $50 balance that is 188-320% — account wipe guaranteed.
    # Bot returns 0 here → main.py sees lot=0 and skips the trade entirely.
    if atr_4h and atr_4h > 0 and balance > 0:
        min_lot_risk_pct = (min_lot * atr_4h * ATR_SL_MULTIPLIER * contract_size / balance) * 100
        if min_lot_risk_pct > 50:
            logger.warning(
                "TRADE BLOCKED [%s]: min lot 0.01 risks %.1f%% of $%.2f balance — "
                "need $%.0f to safely trade this pair (currently have $%.2f)",
                symbol, min_lot_risk_pct, balance,
                (min_lot * atr_4h * ATR_SL_MULTIPLIER * contract_size / 0.20),
                balance,
            )
            return 0   # signals main.py to skip this trade

    # ── Apply day multiplier (Friday = 0.5, Monday = 0.0) ────────
    raw = raw * day_lot_multiplier

    # ── Clamp to min_lot — never go below it ─────────────────────
    raw = max(min_lot, min(max_lot, raw))
    lot = round(math.floor(raw / lot_step) * lot_step, 2)

    # ── Risk warning for small accounts ─────────────────────────
    if atr_4h and atr_4h > 0:
        actual_risk = lot * atr_4h * ATR_SL_MULTIPLIER * contract_size
        risk_pct    = (actual_risk / balance * 100) if balance > 0 else 0
        if risk_pct > 10:
            logger.warning(
                "⚠ HIGH RISK [%s mode]: %s %.2f lot → SL risk = $%.2f (%.1f%% of $%.2f balance)",
                RISK_MODE.upper(), symbol, lot, actual_risk, risk_pct, balance
            )
        else:
            logger.info(
                "Lot [%s]: %s %.2f lot → SL risk = $%.2f (%.1f%% of $%.2f)",
                RISK_MODE.upper(), symbol, lot, actual_risk, risk_pct, balance
            )
    else:
        logger.info("Lot [%s] for %s @ $%.2f balance → %.2f lots", RISK_MODE.upper(), symbol, balance, lot)

    return lot


def calculate_sl_tp(
    action:      str,
    entry_price: float,
    atr_4h:      float,
    symbol:      str,
) -> tuple:
    """
    Returns (sl_price, tp_price).
    SL = ATR × 1.5  |  TP = SL × 2  (2:1 R:R)
    """
    sl_distance = atr_4h * ATR_SL_MULTIPLIER
    tp_distance = sl_distance * RR_RATIO

    if action == "buy":
        sl = entry_price - sl_distance
        tp = entry_price + tp_distance
    else:
        sl = entry_price + sl_distance
        tp = entry_price - tp_distance

    decimals = 2 if "XAU" in symbol else 1
    sl = round(sl, decimals)
    tp = round(tp, decimals)

    logger.info(
        "%s %s | Entry=%.2f | SL=%.2f (±%.2f) | TP=%.2f | ATR=%.2f",
        symbol, action.upper(), entry_price, sl, sl_distance, tp, atr_4h,
    )
    return sl, tp
