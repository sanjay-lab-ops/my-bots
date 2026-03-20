"""
VISHU ELITE BOT — Entry Signal Generator
Final entry signal on 1M chart with RSI confirmation and ATR filter.

Rules:
  1. EMA5 crosses EMA20 on 1M chart in the direction of the bias
  2. RSI(14) on 1M must be between 30–70 (not overbought for BUY, not oversold for SELL)
  3. 4H ATR must be > threshold (>20 for Gold, >500 for BTC) — skip choppy markets

Returns: 'BUY', 'SELL', or 'NONE'
"""

import logging
import pandas as pd

from indicators import (
    add_emas, get_rsi_value, get_atr_value, crossover, crossunder, atr
)
from config import SYMBOLS, ATR_PERIOD

logger = logging.getLogger("entry")

RSI_LOW  = 30   # RSI below this = oversold (avoid selling into this)
RSI_HIGH = 70   # RSI above this = overbought (avoid buying into this)
EMA_FAST = 5
EMA_SLOW = 20


def check_entry(
    symbol:   str,
    bias:     str,
    df_1m:    pd.DataFrame,
    df_4h:    pd.DataFrame,
) -> tuple:
    """
    Evaluate entry signal for given symbol and bias direction.

    Args:
        symbol:  'BTCUSD' or 'XAUUSD'
        bias:    'BUY' or 'SELL' (from bias.py)
        df_1m:   1-minute candle DataFrame (min 60 candles)
        df_4h:   4-hour candle DataFrame (for ATR filter)

    Returns:
        (signal: str, atr_val: float, reason: str)
        signal = 'BUY' | 'SELL' | 'NONE'
    """
    if bias not in ("BUY", "SELL"):
        return "NONE", 0.0, f"Bias is {bias} — no entry"

    sym_cfg  = SYMBOLS.get(symbol, {})
    atr_min  = sym_cfg.get("atr_min", 0)

    # ── ATR Filter (4H) ───────────────────────────────────────────
    if df_4h.empty or len(df_4h) < ATR_PERIOD + 2:
        return "NONE", 0.0, "Insufficient 4H data for ATR filter"

    atr_val = get_atr_value(df_4h, ATR_PERIOD)
    if atr_val < atr_min:
        reason = (
            f"ATR filter blocked: 4H ATR={atr_val:.2f} < min={atr_min} "
            f"(choppy market, skipping {symbol})"
        )
        logger.info("ENTRY BLOCKED — %s", reason)
        return "NONE", atr_val, reason

    # ── 1M EMA Cross ──────────────────────────────────────────────
    if df_1m.empty or len(df_1m) < EMA_SLOW + 5:
        return "NONE", atr_val, "Insufficient 1M data for EMA cross"

    df_1m_calc = add_emas(df_1m, fast=EMA_FAST, slow=EMA_SLOW)
    ema5_s     = df_1m_calc["ema5"]
    ema20_s    = df_1m_calc["ema20"]

    LOOKBACK   = 5  # fire if cross happened within last 5 bars
    buy_cross  = bool(crossover(ema5_s,  ema20_s).iloc[-LOOKBACK:].any())
    sell_cross = bool(crossunder(ema5_s, ema20_s).iloc[-LOOKBACK:].any())
    ema5_above = bool(ema5_s.iloc[-1] > ema20_s.iloc[-1])

    if bias == "BUY" and not (buy_cross and ema5_above):
        return "NONE", atr_val, "BUY bias set — waiting for 1M EMA5 to cross above EMA20"
    if bias == "SELL" and not (sell_cross and not ema5_above):
        return "NONE", atr_val, "SELL bias set — waiting for 1M EMA5 to cross below EMA20"

    cross_dir = "above" if bias == "BUY" else "below"
    logger.info("1M EMA5 crossed %s EMA20 — %s trigger fired", cross_dir, bias)

    # ── RSI Filter (1M) ───────────────────────────────────────────
    if len(df_1m) < 20:
        return "NONE", atr_val, "Insufficient 1M data for RSI"

    rsi_val = get_rsi_value(df_1m, period=14)

    if rsi_val < RSI_LOW or rsi_val > RSI_HIGH:
        reason = (
            f"RSI={rsi_val:.1f} is {'overbought' if rsi_val > RSI_HIGH else 'oversold'} "
            f"— outside safe zone [{RSI_LOW}–{RSI_HIGH}], skipping entry"
        )
        logger.info("ENTRY BLOCKED — %s", reason)
        return "NONE", atr_val, reason

    # ── All checks passed ─────────────────────────────────────────
    reason = (
        f"1M EMA5 crossed {cross_dir} EMA20 | RSI={rsi_val:.1f} (safe) | "
        f"4H ATR={atr_val:.2f} (>{atr_min})"
    )
    logger.info("ENTRY SIGNAL: %s %s — %s", bias, symbol, reason)
    return bias, atr_val, reason
