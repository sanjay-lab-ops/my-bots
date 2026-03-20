"""
Fair Value Gap (FVG) Detection — Smart Money Concepts

What is an FVG?
  When price moves very fast, it creates a gap (imbalance) between 3 candles:
    Candle[i-2] high < Candle[i] low  → Bullish FVG (price gapped UP, demand below)
    Candle[i-2] low  > Candle[i] high → Bearish FVG (price gapped DOWN, supply above)

  Institutions will often send price back into these gaps to:
    1. Fill their own unfilled orders from the fast move
    2. Trap retail traders who chased the breakout

  We enter at the FVG midpoint when price returns to it — same as OB logic.
"""

import pandas as pd
from indicators import atr as calc_atr
from config import FVG_MIN_RATIO, ATR_PERIOD


def find_fvgs(df: pd.DataFrame) -> list:
    """
    Find all unmitigated Fair Value Gaps in df.

    Returns list of dicts:
        type    : "bullish" | "bearish"
        top     : upper boundary of gap
        bottom  : lower boundary of gap
        mid     : midpoint
        time    : timestamp of middle candle
        filled  : True if price has since traded through the entire gap
    """
    if df is None or len(df) < 10:
        return []

    atr_series = calc_atr(df, ATR_PERIOD)
    fvgs       = []
    current_p  = df["close"].iloc[-1]

    for i in range(2, len(df)):
        atr_v = atr_series.iloc[i]
        if atr_v == 0:
            continue

        c0 = df.iloc[i - 2]   # oldest of the 3
        c2 = df.iloc[i]       # newest

        gap_min = atr_v * FVG_MIN_RATIO

        # ── Bullish FVG: gap between c0.high and c2.low ──
        if c2["low"] > c0["high"]:
            gap_size = c2["low"] - c0["high"]
            if gap_size >= gap_min:
                top    = c2["low"]
                bottom = c0["high"]
                # Filled = price has since traded below c0.high (into the gap)
                filled = current_p < bottom
                fvgs.append({
                    "type":    "bullish",
                    "top":     round(top,    5),
                    "bottom":  round(bottom, 5),
                    "mid":     round((top + bottom) / 2, 5),
                    "time":    df.index[i - 1],
                    "filled":  filled,
                    "gap_size": gap_size,
                })

        # ── Bearish FVG: gap between c0.low and c2.high ──
        elif c2["high"] < c0["low"]:
            gap_size = c0["low"] - c2["high"]
            if gap_size >= gap_min:
                top    = c0["low"]
                bottom = c2["high"]
                # Filled = price has since traded above c0.low (into the gap)
                filled = current_p > top
                fvgs.append({
                    "type":   "bearish",
                    "top":    round(top,    5),
                    "bottom": round(bottom, 5),
                    "mid":    round((top + bottom) / 2, 5),
                    "time":   df.index[i - 1],
                    "filled": filled,
                    "gap_size": gap_size,
                })

    return fvgs


def find_nearest_fvg(fvgs: list, current_price: float, direction: str):
    """
    Find closest unfilled FVG aligned with direction.

    For BUY  : nearest unfilled bullish FVG below current price
    For SELL : nearest unfilled bearish FVG above current price
    """
    candidates = []
    for fvg in fvgs:
        if fvg["filled"]:
            continue
        if direction == "buy" and fvg["type"] == "bullish":
            if fvg["top"] < current_price:
                dist = current_price - fvg["mid"]
                candidates.append((dist, fvg))
        elif direction == "sell" and fvg["type"] == "bearish":
            if fvg["bottom"] > current_price:
                dist = fvg["mid"] - current_price
                candidates.append((dist, fvg))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0])   # nearest first
    return candidates[0][1]
