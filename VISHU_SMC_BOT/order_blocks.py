"""
Order Block Detection — Smart Money Concepts

What is an Order Block?
  Institutions cannot buy/sell millions of dollars in one candle — they spread
  their orders over time. The LAST candle opposing the direction before a strong
  move is where institutions placed their orders. When price returns to this
  zone, institutions add more → price bounces strongly.

  Bullish OB: Last RED candle before a big UP move (institutions bought here)
  Bearish OB: Last GREEN candle before a big DOWN move (institutions sold here)

  We place LIMIT orders at the OB midpoint and wait for price to return.
  This is the opposite of retail (who chase the breakout and get trapped).
"""

import numpy as np
import pandas as pd
from indicators import atr as calc_atr
from config import OB_LOOKBACK, ATR_PERIOD


def find_order_blocks(df: pd.DataFrame, trend: str) -> list:
    """
    Find all valid order blocks in df aligned with trend.

    Args:
        df    : OHLCV DataFrame (H4 recommended)
        trend : "bullish" or "bearish"

    Returns list of dicts:
        type     : "bullish" | "bearish"
        top      : upper boundary
        bottom   : lower boundary
        mid      : midpoint (entry price for limit order)
        time     : timestamp of OB candle
        fresh    : True if price hasn't returned to OB yet
        strength : 1–3 (how big the move was after OB)
        atr_at_ob: ATR value when OB formed
    """
    if df is None or len(df) < 20:
        return []

    atr_series = calc_atr(df, ATR_PERIOD)
    obs        = []
    lookback   = min(OB_LOOKBACK, len(df) - 5)
    current_p  = df["close"].iloc[-1]

    for i in range(lookback, len(df) - 3):
        candle = df.iloc[i]
        atr_v  = atr_series.iloc[i]
        if atr_v == 0:
            continue

        is_bull_candle = candle["close"] > candle["open"]
        is_bear_candle = candle["close"] < candle["open"]

        # ── Bullish OB: last bearish candle before significant upward move ──
        if trend == "bullish" and is_bear_candle:
            # Measure the move in the 3 candles after this one
            move_high  = df["high"].iloc[i+1:i+4].max()
            move_after = move_high - candle["high"]
            if move_after >= atr_v * 1.0:   # at least 1× ATR move up after OB
                strength = 3 if move_after >= atr_v * 3 else (2 if move_after >= atr_v * 2 else 1)
                ob_top   = candle["high"]
                ob_bot   = candle["low"]
                fresh    = current_p > ob_top  # price hasn't returned yet
                obs.append({
                    "type":      "bullish",
                    "top":       round(ob_top,  5),
                    "bottom":    round(ob_bot,  5),
                    "mid":       round((ob_top + ob_bot) / 2, 5),
                    "time":      df.index[i],
                    "fresh":     fresh,
                    "strength":  strength,
                    "atr_at_ob": atr_v,
                })

        # ── Bearish OB: last bullish candle before significant downward move ──
        elif trend == "bearish" and is_bull_candle:
            move_low   = df["low"].iloc[i+1:i+4].min()
            move_after = candle["low"] - move_low
            if move_after >= atr_v * 1.0:
                strength = 3 if move_after >= atr_v * 3 else (2 if move_after >= atr_v * 2 else 1)
                ob_top   = candle["high"]
                ob_bot   = candle["low"]
                fresh    = current_p < ob_bot  # price hasn't returned yet
                obs.append({
                    "type":     "bearish",
                    "top":      round(ob_top, 5),
                    "bottom":   round(ob_bot, 5),
                    "mid":      round((ob_top + ob_bot) / 2, 5),
                    "time":     df.index[i],
                    "fresh":    fresh,
                    "strength": strength,
                    "atr_at_ob": atr_v,
                })

    return obs


def find_nearest_ob(obs: list, current_price: float, direction: str,
                    max_distance_pct: float = 5.0):
    """
    Find the best (freshest, strongest, nearest) order block for entry.

    For BUY: nearest FRESH bullish OB below current price
    For SELL: nearest FRESH bearish OB above current price

    max_distance_pct: OB must be within this % of current price.
    Prevents placing limit orders at levels from months ago that price
    won't realistically return to.

    Returns OB dict or None.
    """
    candidates = []
    max_dist   = current_price * (max_distance_pct / 100)

    for ob in obs:
        if not ob["fresh"]:
            continue
        if direction == "buy" and ob["type"] == "bullish":
            if ob["top"] < current_price:
                dist = current_price - ob["mid"]
                if dist <= max_dist:   # within 5% of current price
                    candidates.append((dist, ob))
        elif direction == "sell" and ob["type"] == "bearish":
            if ob["bottom"] > current_price:
                dist = ob["mid"] - current_price
                if dist <= max_dist:   # within 5% of current price
                    candidates.append((dist, ob))

    if not candidates:
        return None

    # Sort: prefer high strength, then proximity
    candidates.sort(key=lambda x: (-(x[1]["strength"]), x[0]))
    return candidates[0][1]
