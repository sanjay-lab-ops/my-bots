"""
Market Structure Analysis — Smart Money Concepts
Identifies trend direction, Break of Structure (BOS), and Change of Character (CHoCH).

Institutional context:
  - Institutions only trade WITH the trend
  - BOS confirms trend continuation → add to position
  - CHoCH = first warning trend is reversing → tighten SL, reduce risk
"""

import numpy as np
import pandas as pd
from indicators import swing_highs, swing_lows
from config import SWING_LOOKBACK


def analyze_structure(df: pd.DataFrame) -> dict:
    """
    Analyze market structure on the given DataFrame (use H4 for bias).

    Returns dict:
        trend         : "bullish" | "bearish" | "ranging"
        last_sh       : last swing high price
        last_sl       : last swing low price
        prev_sh       : previous swing high (to detect BOS)
        prev_sl       : previous swing low
        bos           : True if latest candle broke structure in trend direction
        choch         : True if latest candle shows change of character
        structure_note: human-readable explanation
    """
    if df is None or len(df) < SWING_LOOKBACK * 3:
        return {"trend": "ranging", "last_sh": None, "last_sl": None,
                "prev_sh": None, "prev_sl": None, "bos": False, "choch": False,
                "structure_note": "Insufficient data"}

    sh_series = swing_highs(df, SWING_LOOKBACK)
    sl_series = swing_lows(df,  SWING_LOOKBACK)

    sh_prices = sh_series.dropna().values
    sl_prices = sl_series.dropna().values

    if len(sh_prices) < 2 or len(sl_prices) < 2:
        return {"trend": "ranging", "last_sh": None, "last_sl": None,
                "prev_sh": None, "prev_sl": None, "bos": False, "choch": False,
                "structure_note": "Not enough swings"}

    last_sh = sh_prices[-1]
    prev_sh = sh_prices[-2]
    last_sl = sl_prices[-1]
    prev_sl = sl_prices[-2]

    current_price = df["close"].iloc[-1]

    # Determine trend from swing sequence
    hh = last_sh > prev_sh   # higher high
    hl = last_sl > prev_sl   # higher low
    lh = last_sh < prev_sh   # lower high
    ll = last_sl < prev_sl   # lower low

    if hh and hl:
        trend = "bullish"
    elif lh and ll:
        trend = "bearish"
    elif hh and ll:
        trend = "ranging"  # expanding
    elif lh and hl:
        trend = "ranging"  # contracting
    else:
        trend = "ranging"

    # Break of Structure (BOS) — price closes beyond last swing in trend direction
    bos   = False
    choch = False
    note  = f"Trend={trend.upper()} | SH={last_sh:.2f} SL={last_sl:.2f}"

    if trend == "bullish":
        bos   = current_price > last_sh          # broke above swing high → BOS up
        choch = current_price < last_sl          # broke below swing low → CHoCH (danger)
        if bos:   note += " | BOS ↑ (continuation)"
        if choch: note += " | CHoCH ↓ (reversal warning)"
    elif trend == "bearish":
        bos   = current_price < last_sl          # broke below swing low → BOS down
        choch = current_price > last_sh          # broke above swing high → CHoCH (danger)
        if bos:   note += " | BOS ↓ (continuation)"
        if choch: note += " | CHoCH ↑ (reversal warning)"

    return {
        "trend":          trend,
        "last_sh":        last_sh,
        "last_sl":        last_sl,
        "prev_sh":        prev_sh,
        "prev_sl":        prev_sl,
        "bos":            bos,
        "choch":          choch,
        "structure_note": note,
    }
