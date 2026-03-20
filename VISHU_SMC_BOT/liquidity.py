"""
Liquidity Pool Detection — Smart Money Concepts

What are Liquidity Pools?
  Retail traders place stop losses in predictable locations:
    - Just above equal highs (buy stops)
    - Just below equal lows  (sell stops)
    - Previous day/week high and low

  Institutions SWEEP these levels to fill their large orders cheaply,
  then reverse direction. This is the "stop hunt" or "liquidity grab".

  We use these levels as TP targets — institutions drive price TO these
  pools to collect liquidity, then often reverse.
"""

import numpy as np
import pandas as pd
from indicators import swing_highs, swing_lows
from config import SWING_LOOKBACK, LIQUIDITY_EQ


def find_liquidity_pools(df: pd.DataFrame) -> dict:
    """
    Identify liquidity clusters, prev day/week levels.

    Returns:
        buy_side   : list of prices where stop buy orders are clustered (equal highs)
        sell_side  : list of prices where stop sell orders are clustered (equal lows)
        pdh        : previous day high
        pdl        : previous day low
        pwh        : previous week high
        pwl        : previous week low
    """
    result = {
        "buy_side":  [],
        "sell_side": [],
        "pdh": None,
        "pdl": None,
        "pwh": None,
        "pwl": None,
    }

    if df is None or len(df) < 20:
        return result

    sh = swing_highs(df, SWING_LOOKBACK).dropna().values
    sl = swing_lows( df, SWING_LOOKBACK).dropna().values

    # Equal highs — buy-side liquidity (stop buys cluster here)
    buy_pools = _cluster_levels(sh, LIQUIDITY_EQ)
    result["buy_side"] = sorted(buy_pools)

    # Equal lows — sell-side liquidity (stop sells cluster here)
    sell_pools = _cluster_levels(sl, LIQUIDITY_EQ)
    result["sell_side"] = sorted(sell_pools, reverse=True)

    # Previous day high/low (if D1 data passed — detect from index)
    try:
        today     = df.index[-1].normalize()
        yesterday = today - pd.Timedelta(days=1)
        prev_day  = df[df.index.normalize() == yesterday]
        if not prev_day.empty:
            result["pdh"] = float(prev_day["high"].max())
            result["pdl"] = float(prev_day["low"].min())
    except Exception:
        pass

    # Previous week high/low
    try:
        this_week = df.index[-1].isocalendar().week
        prev_week_df = df[df.index.map(lambda x: x.isocalendar().week) == this_week - 1]
        if not prev_week_df.empty:
            result["pwh"] = float(prev_week_df["high"].max())
            result["pwl"] = float(prev_week_df["low"].min())
    except Exception:
        pass

    return result


def _cluster_levels(levels: np.ndarray, tolerance_pct: float) -> list:
    """Group levels that are within tolerance_pct% of each other. Return cluster midpoints."""
    if len(levels) == 0:
        return []
    clusters = []
    visited  = [False] * len(levels)
    for i, lv in enumerate(levels):
        if visited[i]:
            continue
        group = [lv]
        for j in range(i + 1, len(levels)):
            if not visited[j] and abs(levels[j] - lv) / lv * 100 <= tolerance_pct:
                group.append(levels[j])
                visited[j] = True
        if len(group) >= 2:   # only count as liquidity if at least 2 touches
            clusters.append(float(np.mean(group)))
        visited[i] = True
    return clusters


def find_tp_target(liquidity: dict, direction: str, current_price: float) -> float | None:
    """
    Select the nearest relevant liquidity pool as TP target.

    BUY  → target the nearest buy-side pool ABOVE current price
    SELL → target the nearest sell-side pool BELOW current price

    Falls back to prev day high/low if no pool found.
    """
    if direction == "buy":
        candidates = [p for p in liquidity["buy_side"] if p > current_price]
        if liquidity["pdh"] and liquidity["pdh"] > current_price:
            candidates.append(liquidity["pdh"])
        if liquidity["pwh"] and liquidity["pwh"] > current_price:
            candidates.append(liquidity["pwh"])
        return float(min(candidates)) if candidates else None

    else:  # sell
        candidates = [p for p in liquidity["sell_side"] if p < current_price]
        if liquidity["pdl"] and liquidity["pdl"] < current_price:
            candidates.append(liquidity["pdl"])
        if liquidity["pwl"] and liquidity["pwl"] < current_price:
            candidates.append(liquidity["pwl"])
        return float(max(candidates)) if candidates else None
