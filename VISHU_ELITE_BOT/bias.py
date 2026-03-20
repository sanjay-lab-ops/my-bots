"""
VISHU ELITE BOT — Triple Timeframe Bias Engine
4H + 1H + 15M confluence — ALL THREE must agree for a valid bias.

Rules:
  4H : price above VWAP AND above PVWAP → BUY bias
       price below VWAP AND below PVWAP → SELL bias
       price between them → NEUTRAL (skip)

  1H : EMA20 slope — if rising → bullish, if falling → bearish
       Must match 4H bias.

  15M: EMA5 above EMA20 → bullish, EMA5 below EMA20 → bearish
       Must match 4H and 1H.

Returns: 'BUY', 'SELL', or 'NEUTRAL'
"""

import logging
import math
import pandas as pd

from indicators import add_emas, add_vwap, add_pvwap, ema, ema_slope

logger = logging.getLogger("bias")

# EMA periods used within this module
EMA20 = 20
EMA5  = 5


def _get_4h_bias(df_4h: pd.DataFrame) -> tuple:
    """
    Determine 4H bias using VWAP and PVWAP.
    Returns (bias: str, reason: str) where bias is 'BUY', 'SELL', or 'NEUTRAL'.
    """
    df = add_vwap(df_4h)
    df = add_pvwap(df)

    last  = df.iloc[-1]
    vwap  = last.get("vwap",  float("nan"))
    pvwap = last.get("pvwap", float("nan"))
    price = float(last["close"])

    if math.isnan(vwap) or math.isnan(pvwap):
        return "NEUTRAL", "VWAP/PVWAP not ready (insufficient 4H data)"

    if price > vwap and price > pvwap:
        reason = f"4H: price {price:.2f} > VWAP {vwap:.2f} and PVWAP {pvwap:.2f}"
        return "BUY", reason
    elif price < vwap and price < pvwap:
        reason = f"4H: price {price:.2f} < VWAP {vwap:.2f} and PVWAP {pvwap:.2f}"
        return "SELL", reason
    else:
        reason = (
            f"4H: price {price:.2f} between VWAP {vwap:.2f} and PVWAP {pvwap:.2f} — NEUTRAL"
        )
        return "NEUTRAL", reason


def _get_1h_bias(df_1h: pd.DataFrame, required_bias: str) -> tuple:
    """
    Determine 1H bias using EMA20 slope.
    'rising' slope → BUY, 'falling' slope → SELL.
    Returns (matches: bool, reason: str).
    """
    df       = add_emas(df_1h, fast=EMA5, slow=EMA20)
    ema20_s  = df["ema20"]
    slope    = ema_slope(ema20_s, lookback=3)

    if slope == "rising":
        bias_1h = "BUY"
    elif slope == "falling":
        bias_1h = "SELL"
    else:
        bias_1h = "NEUTRAL"

    matches = bias_1h == required_bias
    reason  = f"1H: EMA20 slope={slope} → bias={bias_1h}"
    return matches, bias_1h, reason


def _get_15m_bias(df_15m: pd.DataFrame, required_bias: str) -> tuple:
    """
    Determine 15M bias using EMA5 vs EMA20 position.
    EMA5 > EMA20 → BUY, EMA5 < EMA20 → SELL.
    Returns (matches: bool, bias: str, reason: str).
    """
    df    = add_emas(df_15m, fast=EMA5, slow=EMA20)
    last  = df.iloc[-1]
    ema5_val  = float(last["ema5"])
    ema20_val = float(last["ema20"])

    if ema5_val > ema20_val:
        bias_15m = "BUY"
    elif ema5_val < ema20_val:
        bias_15m = "SELL"
    else:
        bias_15m = "NEUTRAL"

    matches = bias_15m == required_bias
    reason  = f"15M: EMA5={ema5_val:.2f} {'>' if ema5_val > ema20_val else '<'} EMA20={ema20_val:.2f} → bias={bias_15m}"
    return matches, bias_15m, reason


def get_bias(df_4h: pd.DataFrame, df_1h: pd.DataFrame, df_15m: pd.DataFrame) -> tuple:
    """
    Timeframe confluence check — 4H is mandatory, need 1 of 2 lower TFs to confirm.
    4H VWAP/PVWAP must give a clear direction.
    Then either 1H OR 15M must agree (not required both).

    Returns:
        (bias: str, confirmations: list[str])
        bias = 'BUY' | 'SELL' | 'NEUTRAL'
    """
    confirmations = []

    # ── Step 1: 4H VWAP/PVWAP bias — mandatory ───────────────────
    bias_4h, reason_4h = _get_4h_bias(df_4h)
    confirmations.append(reason_4h)

    if bias_4h == "NEUTRAL":
        logger.info("BIAS: NEUTRAL — %s", reason_4h)
        return "NEUTRAL", confirmations

    # ── Step 2: Check 1H and 15M — need at least 1 to agree ──────
    matches_1h,  bias_1h,  reason_1h  = _get_1h_bias(df_1h,  bias_4h)
    matches_15m, bias_15m, reason_15m = _get_15m_bias(df_15m, bias_4h)
    confirmations.append(reason_1h)
    confirmations.append(reason_15m)

    if not matches_1h and not matches_15m:
        logger.info(
            "BIAS: NEUTRAL — neither 1H (%s) nor 15M (%s) confirms 4H %s",
            bias_1h, bias_15m, bias_4h,
        )
        return "NEUTRAL", confirmations

    confirmed_by = []
    if matches_1h:  confirmed_by.append("1H")
    if matches_15m: confirmed_by.append("15M")

    logger.info(
        "BIAS: %s confirmed — 4H VWAP + %s agree",
        bias_4h, " + ".join(confirmed_by),
    )
    return bias_4h, confirmations
